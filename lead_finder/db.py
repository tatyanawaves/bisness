"""
База данных SQLite: найденные компании, анализы, скрипты звонков.
"""

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    city TEXT NOT NULL,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    address TEXT DEFAULT '',
    phones TEXT DEFAULT '[]',
    website TEXT DEFAULT '',
    email TEXT DEFAULT '',
    rubrics TEXT DEFAULT '[]',
    lat REAL,
    lng REAL,
    rating REAL,
    reviews_count INTEGER,
    branch_count INTEGER,
    map_url TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    worked_at TEXT,
    first_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_businesses_city ON businesses (city, status);
CREATE INDEX IF NOT EXISTS idx_businesses_name_key ON businesses (city, name_key);

CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY,
    input_hash TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    url TEXT DEFAULT '',
    offer TEXT DEFAULT '',
    data TEXT NOT NULL,
    is_ai INTEGER NOT NULL,
    model TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses (id),
    profile_id INTEGER NOT NULL REFERENCES profiles (id),
    data TEXT NOT NULL,
    is_ai INTEGER NOT NULL,
    model TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analyses_lookup ON analyses (business_id, profile_id);

CREATE TABLE IF NOT EXISTS scripts (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses (id),
    profile_id INTEGER NOT NULL REFERENCES profiles (id),
    analysis_id INTEGER REFERENCES analyses (id),
    manager_name TEXT DEFAULT '',
    content TEXT NOT NULL,
    plain_text TEXT NOT NULL,
    is_ai INTEGER NOT NULL,
    model TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scripts_business ON scripts (business_id);

CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY,
    city TEXT NOT NULL,
    params TEXT NOT NULL,
    found INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""

# Организационные формы не считаем частью названия при сравнении компаний
_LEGAL_FORMS = re.compile(
    r"\b(тоо|ао|ип|ооо|зао|пао|оао|жшс|ақ|кх|гкп|ргп|кгп|филиал|llp|jsc|ltd|llc)\b"
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def name_key(name: str) -> str:
    """Ключ названия: одна компания с разными написаниями и формами даёт один ключ."""
    text = (name or "").lower().replace("ё", "е")
    stripped = re.sub(r"[^\w]+", "", _LEGAL_FORMS.sub(" ", text))
    return stripped or re.sub(r"[^\w]+", "", text)


def phone_key(phone: str) -> str:
    """Последние 10 цифр номера: 8 (701) ... и +7 701 ... считаются одним номером."""
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 10 else ""


def _connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session():
    """Короткая транзакция: фиксируется при выходе, откатывается при ошибке."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with session() as conn:
        conn.executescript(SCHEMA)


# ============================================================
# КОМПАНИИ
# ============================================================

def _business_row(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["phones"] = json.loads(item["phones"] or "[]")
    item["rubrics"] = json.loads(item["rubrics"] or "[]")
    return item


def upsert_business(conn: sqlite3.Connection, biz: dict, city: str) -> dict:
    """Сохраняет компанию. Отметка об отработке при обновлении не меняется."""
    stamp = now()
    conn.execute(
        """
        INSERT INTO businesses (source, source_id, city, name, name_key, address, phones, website,
            email, rubrics, lat, lng, rating, reviews_count, branch_count, map_url,
            first_seen_at, updated_at)
        VALUES (:source, :source_id, :city, :name, :name_key, :address, :phones, :website,
            :email, :rubrics, :lat, :lng, :rating, :reviews_count, :branch_count, :map_url,
            :stamp, :stamp)
        ON CONFLICT (source, source_id) DO UPDATE SET
            name = excluded.name, name_key = excluded.name_key, address = excluded.address,
            phones = excluded.phones, website = excluded.website, email = excluded.email,
            rubrics = excluded.rubrics, lat = excluded.lat, lng = excluded.lng,
            rating = excluded.rating, reviews_count = excluded.reviews_count,
            branch_count = excluded.branch_count, map_url = excluded.map_url,
            updated_at = excluded.updated_at
        """,
        {
            "source": biz["source"],
            "source_id": biz["source_id"],
            "city": city,
            "name": biz["name"],
            "name_key": name_key(biz.get("org_name") or biz["name"]),
            "address": biz.get("address", ""),
            "phones": json.dumps(biz.get("phones", []), ensure_ascii=False),
            "website": biz.get("website", ""),
            "email": biz.get("email", ""),
            "rubrics": json.dumps(biz.get("rubrics", []), ensure_ascii=False),
            "lat": biz.get("lat"),
            "lng": biz.get("lng"),
            "rating": biz.get("rating"),
            "reviews_count": biz.get("reviews_count"),
            "branch_count": biz.get("branch_count"),
            "map_url": biz.get("map_url", ""),
            "stamp": stamp,
        },
    )
    row = conn.execute(
        "SELECT * FROM businesses WHERE source = ? AND source_id = ?",
        (biz["source"], biz["source_id"]),
    ).fetchone()
    return _business_row(row)


def get_business(conn: sqlite3.Connection, business_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM businesses WHERE id = ?", (business_id,)).fetchone()
    return _business_row(row) if row else None


def worked_index(conn: sqlite3.Connection, city: str) -> dict:
    """
    Что считать уже отработанным в городе: запись источника, название или телефон.
    Название и телефон нужны, чтобы компания не вернулась через другой источник или филиал.
    """
    index = {"sources": set(), "names": set(), "phones": set()}
    rows = conn.execute(
        "SELECT source, source_id, name_key, phones FROM businesses WHERE status = 'worked' AND city = ?",
        (city,),
    ).fetchall()
    for row in rows:
        index["sources"].add((row["source"], row["source_id"]))
        index["names"].add(row["name_key"])
        for phone in json.loads(row["phones"] or "[]"):
            key = phone_key(phone)
            if key:
                index["phones"].add(key)
    return index


def is_worked(biz: dict, index: dict) -> bool:
    if (biz["source"], biz["source_id"]) in index["sources"]:
        return True
    if name_key(biz.get("org_name") or biz["name"]) in index["names"]:
        return True
    return any(phone_key(phone) in index["phones"] for phone in biz.get("phones", []) if phone_key(phone))


def set_worked(conn: sqlite3.Connection, business_id: int, worked: bool) -> dict | None:
    """Отмечает компанию отработанной или возвращает её в поиск."""
    conn.execute(
        "UPDATE businesses SET status = ?, worked_at = ?, updated_at = ? WHERE id = ?",
        ("worked" if worked else "new", now() if worked else None, now(), business_id),
    )
    return get_business(conn, business_id)


def list_worked(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM businesses WHERE status = 'worked' ORDER BY worked_at DESC"
    ).fetchall()
    return [_business_row(row) for row in rows]


# ============================================================
# ПРОФИЛИ НАШЕЙ КОМПАНИИ
# ============================================================

def _profile_row(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["data"] = json.loads(item["data"])
    return item


def get_profile_by_hash(conn: sqlite3.Connection, input_hash: str) -> dict | None:
    row = conn.execute("SELECT * FROM profiles WHERE input_hash = ?", (input_hash,)).fetchone()
    return _profile_row(row) if row else None


def get_profile(conn: sqlite3.Connection, profile_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    return _profile_row(row) if row else None


def save_profile(conn, input_hash, description, url, offer, data, is_ai, model) -> dict:
    """Сохраняет разбор компании. Повторный разбор тех же данных заменяет прежний."""
    conn.execute(
        """
        INSERT INTO profiles (input_hash, description, url, offer, data, is_ai, model, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (input_hash) DO UPDATE SET
            data = excluded.data, is_ai = excluded.is_ai, model = excluded.model,
            created_at = excluded.created_at
        """,
        (input_hash, description, url, offer, json.dumps(data, ensure_ascii=False), int(is_ai), model, now()),
    )
    return get_profile_by_hash(conn, input_hash)


def list_profiles(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = conn.execute("SELECT * FROM profiles ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_profile_row(row) for row in rows]


# ============================================================
# АНАЛИЗЫ И СКРИПТЫ
# ============================================================

def _analysis_row(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["data"] = json.loads(item["data"])
    return item


def latest_analysis(conn: sqlite3.Connection, business_id: int, profile_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM analyses WHERE business_id = ? AND profile_id = ? ORDER BY id DESC LIMIT 1",
        (business_id, profile_id),
    ).fetchone()
    return _analysis_row(row) if row else None


def save_analysis(conn, business_id, profile_id, data, is_ai, model) -> dict:
    cursor = conn.execute(
        "INSERT INTO analyses (business_id, profile_id, data, is_ai, model, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (business_id, profile_id, json.dumps(data, ensure_ascii=False), int(is_ai), model, now()),
    )
    row = conn.execute("SELECT * FROM analyses WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _analysis_row(row)


def list_analyses(conn: sqlite3.Connection, limit: int = 200) -> list[dict]:
    rows = conn.execute(
        """
        SELECT a.*, b.name AS business_name, b.city AS city, b.status AS business_status
        FROM analyses a JOIN businesses b ON b.id = a.business_id
        ORDER BY a.id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_analysis_row(row) for row in rows]


def save_script(conn, business_id, profile_id, analysis_id, manager_name, content, plain_text, is_ai, model) -> dict:
    cursor = conn.execute(
        """
        INSERT INTO scripts (business_id, profile_id, analysis_id, manager_name, content, plain_text,
            is_ai, model, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            business_id, profile_id, analysis_id, manager_name,
            json.dumps(content, ensure_ascii=False), plain_text, int(is_ai), model, now(),
        ),
    )
    return get_script(conn, cursor.lastrowid)


def get_script(conn: sqlite3.Connection, script_id: int) -> dict | None:
    row = conn.execute(
        """
        SELECT s.*, b.name AS business_name, b.city AS city, b.status AS business_status
        FROM scripts s JOIN businesses b ON b.id = s.business_id WHERE s.id = ?
        """,
        (script_id,),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["content"] = json.loads(item["content"])
    return item


def list_scripts(conn: sqlite3.Connection, limit: int = 200) -> list[dict]:
    rows = conn.execute(
        """
        SELECT s.id, s.business_id, s.profile_id, s.is_ai, s.model, s.created_at,
            b.name AS business_name, b.city AS city, b.status AS business_status
        FROM scripts s JOIN businesses b ON b.id = s.business_id
        ORDER BY s.id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def log_search(conn: sqlite3.Connection, city: str, params: dict, found: int) -> None:
    conn.execute(
        "INSERT INTO searches (city, params, found, created_at) VALUES (?, ?, ?, ?)",
        (city, json.dumps(params, ensure_ascii=False), found, now()),
    )
