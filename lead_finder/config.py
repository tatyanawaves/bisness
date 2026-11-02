"""
Конфигурация помощника по поиску клиентов.
Все ключи берутся из переменных окружения или файла .env.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Сначала .env этой папки, затем общий .env проекта
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env")

# ============================================================
# МОДЕЛЬ (бесплатный тариф Groq: https://console.groq.com/keys)
# ============================================================
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")

# ============================================================
# КАРТЫ
# ============================================================
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
GOOGLE_PLACES_BASE_URL = os.getenv("GOOGLE_PLACES_BASE_URL", "https://places.googleapis.com/v1")
GOOGLE_LEGACY_BASE_URL = os.getenv("GOOGLE_LEGACY_BASE_URL", "https://maps.googleapis.com/maps/api/place")

DGIS_API_KEY = os.getenv("DGIS_API_KEY", "")
DGIS_BASE_URL = os.getenv("DGIS_BASE_URL", "https://catalog.api.2gis.com/3.0")

# google или 2gis. Если пусто: Google при наличии ключа, иначе 2ГИС
MAP_PROVIDER = os.getenv("MAP_PROVIDER", "").strip().lower()

# Радиус поиска вокруг центра города, км
SEARCH_RADIUS_KM = 30

# ============================================================
# ПРИЛОЖЕНИЕ
# ============================================================
DB_PATH = Path(os.getenv("LEAD_FINDER_DB", BASE_DIR / "data" / "leads.db"))
HOST = os.getenv("LEAD_FINDER_HOST", "127.0.0.1")
PORT = int(os.getenv("LEAD_FINDER_PORT", "5050"))
