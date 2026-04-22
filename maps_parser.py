"""
Модуль парсинга бизнесов с Google Maps (Places API).
Собирает: название, сфера, адрес, телефон, сайт, рейтинг, отзывы.
"""

import requests
from config import GOOGLE_PLACES_API_KEY, SEARCH_LOCATIONS, DEFAULT_CITY, SEARCH_RADIUS, MAX_RESULTS


def search_businesses(query: str, city: str = DEFAULT_CITY) -> list[dict]:
    """
    Поиск бизнесов через Google Places Text Search API.

    Args:
        query: Поисковый запрос (напр. "кофейня", "барбершоп", "стоматология")
        city: Город из SEARCH_LOCATIONS

    Returns:
        Список словарей с данными бизнесов
    """
    location = SEARCH_LOCATIONS.get(city, SEARCH_LOCATIONS[DEFAULT_CITY])

    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        "query": f"{query} {city}",
        "location": f"{location['lat']},{location['lng']}",
        "radius": SEARCH_RADIUS,
        "language": "ru",
        "key": GOOGLE_PLACES_API_KEY,
    }

    all_results = []

    while len(all_results) < MAX_RESULTS:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "OK":
            print(f"[Maps] Статус: {data.get('status')} — {data.get('error_message', '')}")
            break

        for place in data.get("results", []):
            all_results.append({
                "place_id": place.get("place_id"),
                "name": place.get("name", ""),
                "address": place.get("formatted_address", ""),
                "rating": place.get("rating", 0),
                "reviews_count": place.get("user_ratings_total", 0),
                "types": ", ".join(place.get("types", [])),
                "business_status": place.get("business_status", ""),
            })

        # Следующая страница результатов
        next_token = data.get("next_page_token")
        if not next_token or len(all_results) >= MAX_RESULTS:
            break

        import time
        time.sleep(2)  # Google требует задержку перед next_page_token
        params = {"pagetoken": next_token, "key": GOOGLE_PLACES_API_KEY}

    print(f"[Maps] Найдено {len(all_results)} бизнесов по запросу '{query}' в {city}")
    return all_results[:MAX_RESULTS]


def get_place_details(place_id: str) -> dict:
    """
    Получение детальной информации о бизнесе: телефон, сайт, отзывы.
    """
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "fields": "name,formatted_phone_number,website,url,reviews,opening_hours,types",
        "language": "ru",
        "key": GOOGLE_PLACES_API_KEY,
    }

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != "OK":
        return {}

    result = data.get("result", {})

    # Извлекаем топ-3 негативных отзыва (они лучше всего подходят для спитча)
    reviews = result.get("reviews", [])
    negative_reviews = sorted(reviews, key=lambda r: r.get("rating", 5))[:3]
    review_texts = [r.get("text", "") for r in negative_reviews if r.get("text")]

    return {
        "phone": result.get("formatted_phone_number", ""),
        "website": result.get("website", ""),
        "google_maps_url": result.get("url", ""),
        "reviews_sample": " | ".join(review_texts[:2]),  # Берём 2 самых полезных
    }


def parse_maps(queries: list[str], city: str = DEFAULT_CITY) -> list[dict]:
    """
    Основная функция: парсит бизнесы по списку запросов и обогащает деталями.

    Args:
        queries: Список запросов (["кофейня", "барбершоп", "стоматология"])
        city: Город для поиска

    Returns:
        Полный список бизнесов с деталями
    """
    all_businesses = []
    seen_ids = set()

    for query in queries:
        businesses = search_businesses(query, city)

        for biz in businesses:
            pid = biz["place_id"]
            if pid in seen_ids:
                continue
            seen_ids.add(pid)

            # Получаем детали (телефон, сайт, отзывы)
            details = get_place_details(pid)
            biz.update(details)
            biz["search_query"] = query
            all_businesses.append(biz)

            print(f"  + {biz['name']} -- {biz.get('website', 'no site')}")

    print(f"\n[Maps] Итого уникальных бизнесов: {len(all_businesses)}")
    return all_businesses
