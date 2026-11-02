"""
Поиск компаний на картах: Google Places и 2ГИС.
Оба источника приводятся к одному формату записи о компании.
"""

import math
import re
from typing import Iterator

import requests

from . import config

GOOGLE_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.types",
        "places.primaryTypeDisplayName",
        "places.rating",
        "places.userRatingCount",
        "places.businessStatus",
        "places.googleMapsUri",
        "places.websiteUri",
        "places.internationalPhoneNumber",
        "places.nationalPhoneNumber",
        "nextPageToken",
    ]
)
# Google отдаёт по одному запросу не больше трёх страниц
GOOGLE_MAX_PAGES = 3
DGIS_MAX_PAGES = 5
DGIS_PAGE_SIZE = 50
DGIS_FALLBACK_PAGE_SIZE = 10
DGIS_FIELDS = "items.org,items.rubrics,items.point,items.address,items.contact_groups,items.reviews"

_GENERIC_TYPES = {"point_of_interest", "establishment"}

# Демо-ключи 2ГИС принимают меньший размер страницы. Запоминаем, чтобы не тратить лишний запрос на каждый поиск
_dgis_page_size = DGIS_PAGE_SIZE


class MapError(Exception):
    """Источник карт не настроен или отклонил запрос."""


def active_provider() -> str | None:
    """Какой источник использовать: google, 2gis или None, если ключей нет."""
    keys = {"google": config.GOOGLE_PLACES_API_KEY, "2gis": config.DGIS_API_KEY}
    if config.MAP_PROVIDER in keys:
        return config.MAP_PROVIDER if keys[config.MAP_PROVIDER] else None
    if config.GOOGLE_PLACES_API_KEY:
        return "google"
    if config.DGIS_API_KEY:
        return "2gis"
    return None


def provider_label(provider: str | None) -> str:
    return {"google": "Google Places", "2gis": "2ГИС"}.get(provider or "", "не подключены")


def search_pages(phrase: str, city: dict) -> Iterator[list[dict]]:
    """Отдаёт результаты поиска постранично, чтобы не тратить лишние запросы."""
    provider = active_provider()
    if provider == "google":
        yield from _google_pages(phrase, city)
    elif provider == "2gis":
        yield from _dgis_pages(phrase, city)
    else:
        raise MapError("Не задан ключ карт. Добавьте GOOGLE_PLACES_API_KEY или DGIS_API_KEY в .env")


def enrich(biz: dict) -> dict:
    """Догружает телефон и сайт там, где источник не отдаёт их сразу."""
    if biz.get("needs_details"):
        biz.update(_google_legacy_details(biz["source_id"]))
        biz["needs_details"] = False
    return biz


def within_city(biz: dict, city: dict) -> bool:
    """Отсекает то, что карта вернула заметно дальше радиуса поиска."""
    if biz.get("lat") is None or biz.get("lng") is None:
        return True
    return _distance_km(biz["lat"], biz["lng"], city["lat"], city["lng"]) <= config.SEARCH_RADIUS_KM * 1.5


def _distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlng = math.radians(lng2 - lng1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlng / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _rectangle(city: dict) -> dict:
    dlat = config.SEARCH_RADIUS_KM / 111
    dlng = config.SEARCH_RADIUS_KM / (111 * math.cos(math.radians(city["lat"])))
    return {
        "low": {"latitude": city["lat"] - dlat, "longitude": city["lng"] - dlng},
        "high": {"latitude": city["lat"] + dlat, "longitude": city["lng"] + dlng},
    }


# ============================================================
# GOOGLE PLACES (New), при необходимости Legacy
# ============================================================

def _google_error(resp: requests.Response) -> str:
    try:
        return resp.json().get("error", {}).get("message", "") or f"код {resp.status_code}"
    except ValueError:
        return f"код {resp.status_code}"


def _google_denied(new_api_error: str, legacy_error: str = "") -> str:
    """
    Текст ошибки, когда отказали и новая, и старая версия API.
    Новая версия при отключённом биллинге пишет только «нет прав», причину называет старая.
    """
    if "has not been used" in new_api_error or "disabled" in new_api_error:
        link = re.search(r"https://\S*places\.googleapis\.com\S*", new_api_error)
        target = link.group(0) if link else "https://console.cloud.google.com/marketplace/product/google/places.googleapis.com"
        return f"Для этого ключа не включён Places API (New). Включите его: {target}"
    if "billing" in legacy_error.lower() or "billing" in new_api_error.lower():
        return (
            "К проекту Google Cloud не подключён биллинг, без него Places API не работает "
            "даже в пределах бесплатного объёма. Подключите платёжный аккаунт: "
            "https://console.cloud.google.com/project/_/billing/enable"
        )
    return f"Google Places отклонил запрос: {new_api_error}"


def _from_google(place: dict) -> dict:
    rubrics = []
    primary = (place.get("primaryTypeDisplayName") or {}).get("text")
    if primary:
        rubrics.append(primary)
    rubrics += [t for t in place.get("types", []) if t not in _GENERIC_TYPES][:3]
    phone = place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber")
    location = place.get("location") or {}
    return {
        "source": "google",
        "source_id": place["id"],
        "name": (place.get("displayName") or {}).get("text", ""),
        "address": place.get("formattedAddress", ""),
        "phones": [phone] if phone else [],
        "website": place.get("websiteUri", ""),
        "rubrics": rubrics,
        "lat": location.get("latitude"),
        "lng": location.get("longitude"),
        "rating": place.get("rating"),
        "reviews_count": place.get("userRatingCount"),
        "map_url": place.get("googleMapsUri", ""),
    }


def _google_pages(phrase: str, city: dict) -> Iterator[list[dict]]:
    body = {
        "textQuery": f"{phrase} {city['name']}",
        "languageCode": "ru",
        "regionCode": "KZ",
        "pageSize": 20,
        "locationRestriction": {"rectangle": _rectangle(city)},
    }
    headers = {
        "X-Goog-Api-Key": config.GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": GOOGLE_FIELD_MASK,
    }
    for page in range(GOOGLE_MAX_PAGES):
        try:
            resp = requests.post(
                f"{config.GOOGLE_PLACES_BASE_URL}/places:searchText", json=body, headers=headers, timeout=20
            )
        except requests.RequestException as exc:
            raise MapError(f"Google Places недоступен: {type(exc).__name__}") from exc

        # Старые ключи проекта могут быть подключены только к Places API (Legacy)
        if resp.status_code == 403 and page == 0:
            yield from _google_legacy_pages(phrase, city, _google_error(resp))
            return
        if resp.status_code >= 400:
            if page > 0:
                return
            raise MapError(f"Google Places отклонил запрос: {_google_error(resp)}")

        data = resp.json()
        places = [p for p in data.get("places", []) if p.get("businessStatus") != "CLOSED_PERMANENTLY"]
        yield [_from_google(place) for place in places]

        token = data.get("nextPageToken")
        if not token:
            return
        body["pageToken"] = token


def _google_legacy_pages(phrase: str, city: dict, new_api_error: str) -> Iterator[list[dict]]:
    params = {
        "query": f"{phrase} {city['name']}",
        "location": f"{city['lat']},{city['lng']}",
        "radius": config.SEARCH_RADIUS_KM * 1000,
        "language": "ru",
        "key": config.GOOGLE_PLACES_API_KEY,
    }
    for page in range(GOOGLE_MAX_PAGES):
        try:
            resp = requests.get(f"{config.GOOGLE_LEGACY_BASE_URL}/textsearch/json", params=params, timeout=20)
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise MapError(f"Google Places недоступен: {type(exc).__name__}") from exc

        status = data.get("status")
        if status == "ZERO_RESULTS":
            return
        if status != "OK":
            if page > 0:
                return
            raise MapError(_google_denied(new_api_error, data.get("error_message") or ""))

        items = []
        for place in data.get("results", []):
            if place.get("business_status") == "CLOSED_PERMANENTLY":
                continue
            location = (place.get("geometry") or {}).get("location") or {}
            items.append(
                {
                    "source": "google",
                    "source_id": place["place_id"],
                    "name": place.get("name", ""),
                    "address": place.get("formatted_address", ""),
                    "phones": [],
                    "website": "",
                    "rubrics": [t for t in place.get("types", []) if t not in _GENERIC_TYPES][:3],
                    "lat": location.get("lat"),
                    "lng": location.get("lng"),
                    "rating": place.get("rating"),
                    "reviews_count": place.get("user_ratings_total"),
                    "map_url": "",
                    "needs_details": True,
                }
            )
        yield items

        token = data.get("next_page_token")
        if not token:
            return
        params = {"pagetoken": token, "key": config.GOOGLE_PLACES_API_KEY}


def _google_legacy_details(place_id: str) -> dict:
    params = {
        "place_id": place_id,
        "fields": "formatted_phone_number,international_phone_number,website,url",
        "language": "ru",
        "key": config.GOOGLE_PLACES_API_KEY,
    }
    try:
        result = requests.get(f"{config.GOOGLE_LEGACY_BASE_URL}/details/json", params=params, timeout=15).json()
    except (requests.RequestException, ValueError):
        return {}
    if result.get("status") != "OK":
        return {}
    details = result.get("result", {})
    phone = details.get("international_phone_number") or details.get("formatted_phone_number")
    return {
        "phones": [phone] if phone else [],
        "website": details.get("website", ""),
        "map_url": details.get("url", ""),
    }


# ============================================================
# 2ГИС
# ============================================================

def _from_dgis(item: dict) -> dict:
    org = item.get("org") or {}
    point = item.get("point") or {}
    reviews = item.get("reviews") or {}
    firm_id = str(item["id"]).split("_")[0]

    phones, website, email = [], "", ""
    for group in item.get("contact_groups") or []:
        for contact in group.get("contacts") or []:
            kind = contact.get("type")
            if kind == "phone":
                phones.append(contact.get("value") or contact.get("text") or "")
            elif kind == "website" and not website:
                website = contact.get("url") or contact.get("value") or ""
            elif kind == "email" and not email:
                email = contact.get("value") or ""

    return {
        "source": "2gis",
        "source_id": firm_id,
        "name": item.get("name", ""),
        "org_name": org.get("name") or org.get("primary") or "",
        "address": item.get("address_name") or item.get("full_address_name") or "",
        "phones": [phone for phone in phones if phone],
        "website": website,
        "email": email,
        "rubrics": [r.get("name") for r in item.get("rubrics") or [] if r.get("name")],
        "lat": point.get("lat"),
        "lng": point.get("lon"),
        "rating": reviews.get("general_rating"),
        "reviews_count": reviews.get("general_review_count") or reviews.get("review_count"),
        "branch_count": org.get("branch_count"),
        "map_url": f"https://2gis.kz/firm/{firm_id}",
    }


def _dgis_pages(phrase: str, city: dict) -> Iterator[list[dict]]:
    global _dgis_page_size
    params = {
        "q": phrase,
        "type": "branch",
        "point": f"{city['lng']},{city['lat']}",
        "radius": config.SEARCH_RADIUS_KM * 1000,
        "fields": DGIS_FIELDS,
        "page_size": _dgis_page_size,
        "key": config.DGIS_API_KEY,
    }
    page = 1
    while page <= DGIS_MAX_PAGES:
        params["page"] = page
        try:
            data = requests.get(f"{config.DGIS_BASE_URL}/items", params=params, timeout=20).json()
        except (requests.RequestException, ValueError) as exc:
            raise MapError(f"2ГИС недоступен: {type(exc).__name__}") from exc

        meta = data.get("meta") or {}
        code = meta.get("code")
        if code == 404:
            return
        if code == 400 and params["page_size"] != DGIS_FALLBACK_PAGE_SIZE and "page_size" in str(meta.get("error")):
            _dgis_page_size = params["page_size"] = DGIS_FALLBACK_PAGE_SIZE
            continue
        if code != 200:
            if page > 1:
                return
            message = (meta.get("error") or {}).get("message") or f"код {code}"
            raise MapError(f"2ГИС отклонил запрос: {message}")

        result = data.get("result") or {}
        items = result.get("items") or []
        yield [_from_dgis(item) for item in items]

        if page * params["page_size"] >= result.get("total", 0) or not items:
            return
        page += 1
