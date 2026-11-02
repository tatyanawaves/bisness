"""
Помощник по поиску клиентов: веб-интерфейс и API.

Запуск из корня проекта:
    python -m lead_finder.app
"""

import json
import logging

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from . import config, db, llm, maps, prospects, scripts
from .activities import public_list
from .cities import CITIES
from .company import CompanyInputError, analyze_company

logger = logging.getLogger(__name__)

app = Flask(__name__)
db.init_db()


def _public_profile(profile: dict) -> dict:
    return {"id": profile["id"], "is_ai": bool(profile["is_ai"]), "url": profile["url"], **profile["data"]}


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/meta")
def meta():
    """Справочники для формы и состояние ключей."""
    provider = maps.active_provider()
    with db.session() as conn:
        profiles = db.list_profiles(conn, limit=10)
    return jsonify(
        {
            "cities": [city["name"] for city in CITIES],
            "activities": public_list(),
            "sizes": [{"key": key, "label": prospects.SIZE_LABELS[key]} for key in ("ip", "small", "medium", "large")],
            "max_count": prospects.MAX_COUNT,
            "maps": {"provider": provider, "label": maps.provider_label(provider)},
            "llm": {"configured": llm.is_configured(), "model": llm.model_name()},
            "profiles": [_public_profile(profile) for profile in profiles],
        }
    )


@app.post("/api/company/analyze")
def analyze():
    payload = request.get_json(silent=True) or {}
    try:
        profile, warnings = analyze_company(payload.get("company", ""), payload.get("offer", ""))
    except CompanyInputError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"profile": _public_profile(profile), "warnings": warnings})


@app.post("/api/search")
def search():
    """Поиск отдаётся потоком: по одному JSON-событию на строку."""
    try:
        params = prospects.parse_params(request.get_json(silent=True) or {})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    def stream():
        try:
            for event in prospects.run_search(params):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception:
            logger.exception("Поиск завершился ошибкой")
            yield json.dumps({"type": "error", "text": "Поиск прервался из-за внутренней ошибки. Подробности в консоли приложения"}, ensure_ascii=False) + "\n"

    return Response(stream_with_context(stream()), mimetype="application/x-ndjson")


@app.post("/api/businesses/<int:business_id>/worked")
def mark_worked(business_id: int):
    """Отмечает компанию отработанной или возвращает её в поиск."""
    payload = request.get_json(silent=True) or {}
    with db.session() as conn:
        business = db.set_worked(conn, business_id, bool(payload.get("worked", True)))
    if not business:
        return jsonify({"error": "Компания не найдена"}), 404
    return jsonify({"business": business})


@app.get("/api/businesses/worked")
def worked_list():
    with db.session() as conn:
        return jsonify({"businesses": db.list_worked(conn)})


@app.post("/api/businesses/<int:business_id>/script")
def create_script(business_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        script = scripts.generate(business_id, int(payload.get("profile_id") or 0), str(payload.get("manager_name") or ""))
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"script": script})


@app.get("/api/scripts")
def scripts_list():
    with db.session() as conn:
        return jsonify({"scripts": db.list_scripts(conn)})


@app.get("/api/scripts/<int:script_id>")
def script_detail(script_id: int):
    with db.session() as conn:
        script = db.get_script(conn, script_id)
    if not script:
        return jsonify({"error": "Скрипт не найден"}), 404
    return jsonify({"script": script})


@app.get("/api/analyses")
def analyses_list():
    with db.session() as conn:
        return jsonify({"analyses": db.list_analyses(conn)})


if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, threaded=True)
