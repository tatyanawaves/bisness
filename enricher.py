"""
Модуль обогащения данных.
Парсит сайт компании для поиска: имя владельца, email, соцсети.
"""

import re
import requests
from urllib.parse import urljoin


# Паттерны для поиска контактов
EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
PHONE_PATTERN = re.compile(r'[\+]?[78][\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}')
SOCIAL_PATTERNS = {
    "instagram": re.compile(r'(?:instagram\.com|instagr\.am)/([a-zA-Z0-9_.]+)'),
    "whatsapp": re.compile(r'(?:wa\.me|api\.whatsapp\.com/send\?phone=)(\+?\d+)'),
    "telegram": re.compile(r'(?:t\.me|telegram\.me)/([a-zA-Z0-9_]+)'),
}

# Ключевые слова для поиска страниц с контактами
CONTACT_PAGES = ["контакты", "contacts", "about", "о-нас", "о-компании", "команда", "team"]


def _fetch_page(url: str, timeout: int = 10) -> str:
    """Безопасно загружает страницу и возвращает HTML."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        resp.encoding = resp.apparent_encoding
        return resp.text
    except Exception as e:
        print(f"  [Enricher] Ошибка загрузки {url}: {e}")
        return ""


def _find_contact_links(html: str, base_url: str) -> list[str]:
    """Ищет ссылки на страницы контактов/о нас."""
    links = re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE)
    contact_links = []

    for link in links:
        link_lower = link.lower()
        for keyword in CONTACT_PAGES:
            if keyword in link_lower:
                full_url = urljoin(base_url, link)
                if full_url not in contact_links:
                    contact_links.append(full_url)
                break

    return contact_links[:5]  # Макс 5 страниц


def _extract_owner_name(html: str) -> str:
    """
    Пытается найти имя владельца/директора на странице.
    Ищет паттерны: "Директор — Иванов Иван", "Основатель: ..." и т.д.
    """
    patterns = [
        r'(?:директор|основатель|владелец|руководитель|CEO|founder|учредитель)[\s:—\-]+([А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+)',
        r'([А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+)[\s,—\-]+(?:директор|основатель|владелец|руководитель|CEO|founder|учредитель)',
    ]

    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1).strip()

    return ""


def enrich_business(business: dict) -> dict:
    """
    Обогащает данные бизнеса: парсит сайт для поиска контактов владельца.

    Добавляет поля: owner_name, emails, phones, socials
    """
    website = business.get("website", "")
    enriched = {
        "owner_name": "",
        "emails": "",
        "extra_phones": "",
        "instagram": "",
        "whatsapp": "",
        "telegram": "",
    }

    if not website:
        business.update(enriched)
        return business

    # Парсим главную страницу
    html = _fetch_page(website)
    if not html:
        business.update(enriched)
        return business

    # Собираем все страницы для анализа
    all_html = html
    contact_links = _find_contact_links(html, website)
    for link in contact_links:
        page_html = _fetch_page(link)
        all_html += "\n" + page_html

    # Извлекаем данные
    emails = list(set(EMAIL_PATTERN.findall(all_html)))
    # Фильтруем служебные email (png, jpg, etc.)
    emails = [e for e in emails if not e.endswith(('.png', '.jpg', '.svg', '.css', '.js'))]

    phones = list(set(PHONE_PATTERN.findall(all_html)))

    enriched["owner_name"] = _extract_owner_name(all_html)
    enriched["emails"] = ", ".join(emails[:5])
    enriched["extra_phones"] = ", ".join(phones[:3])

    for social_name, pattern in SOCIAL_PATTERNS.items():
        matches = pattern.findall(all_html)
        if matches:
            enriched[social_name] = matches[0]

    business.update(enriched)

    found = [k for k, v in enriched.items() if v]
    if found:
        print(f"  [Enricher] {business['name']}: найдено — {', '.join(found)}")

    return business


def enrich_all(businesses: list[dict]) -> list[dict]:
    """Обогащает весь список бизнесов."""
    print(f"\n[Enricher] Обогащаем данные для {len(businesses)} бизнесов...")

    for i, biz in enumerate(businesses, 1):
        print(f"  [{i}/{len(businesses)}] {biz['name']}...")
        enrich_business(biz)

    enriched_count = sum(1 for b in businesses if b.get("owner_name") or b.get("emails"))
    print(f"[Enricher] Обогащено с контактами: {enriched_count}/{len(businesses)}")

    return businesses
