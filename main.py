"""
Finvy B2B Outreach — Главный скрипт.

Парсит бизнесы с Google Maps → обогащает данные → генерирует спитчи через AI.

Использование:
    python main.py                          # Интерактивный режим
    python main.py --query "кофейня"        # Быстрый запуск
    python main.py --demo                   # Демо без API (тестовые данные)
"""

import argparse
import csv
import sys
import os
import webbrowser
from datetime import datetime

from config import OUTPUT_CSV, OUTPUT_ENCODING, DEFAULT_CITY
from maps_parser import parse_maps
from enricher import enrich_all
from pitch_generator import (
    generate_all_pitches,
    generate_pitch,
    SCENARIOS,
    CHANNELS,
)
from export_html import generate_html


# ============================================================
# ДЕМО-ДАННЫЕ (для тестирования без Google API)
# ============================================================

DEMO_BUSINESSES = [
    {
        "place_id": "demo_1",
        "name": "Кофейня BeanSpot",
        "address": "ул. Кабанбай батыра, 15, Усть-Каменогорск",
        "rating": 4.2,
        "reviews_count": 87,
        "types": "cafe, food, establishment",
        "business_status": "OPERATIONAL",
        "phone": "+7 723 245-12-34",
        "website": "",
        "google_maps_url": "",
        "reviews_sample": "Кофе вкусный, но долго ждать. Официант перепутал заказ.",
        "search_query": "кофейня",
        "owner_name": "",
        "emails": "",
        "extra_phones": "",
        "instagram": "beanspot.ukk",
        "whatsapp": "",
        "telegram": "",
    },
    {
        "place_id": "demo_2",
        "name": "Барбершоп TopCut",
        "address": "пр. Независимости, 42, Усть-Каменогорск",
        "rating": 4.7,
        "reviews_count": 215,
        "types": "hair_care, beauty_salon, establishment",
        "business_status": "OPERATIONAL",
        "phone": "+7 723 298-55-77",
        "website": "https://topcut.kz",
        "google_maps_url": "",
        "reviews_sample": "Лучший барбершоп в городе! Правда, цены выросли.",
        "search_query": "барбершоп",
        "owner_name": "Ермек Сатыбалдиев",
        "emails": "info@topcut.kz",
        "extra_phones": "",
        "instagram": "topcut_ukk",
        "whatsapp": "+77232985577",
        "telegram": "",
    },
    {
        "place_id": "demo_3",
        "name": "Стоматология SmileDent",
        "address": "ул. Тохтарова, 88, Усть-Каменогорск",
        "rating": 4.5,
        "reviews_count": 340,
        "types": "dentist, health, establishment",
        "business_status": "OPERATIONAL",
        "phone": "+7 723 226-00-11",
        "website": "https://smiledent.kz",
        "google_maps_url": "",
        "reviews_sample": "Отличные врачи, но запись за 2 недели. Хотелось бы платить частями.",
        "search_query": "стоматология",
        "owner_name": "Айгуль Нурланова",
        "emails": "clinic@smiledent.kz, hr@smiledent.kz",
        "extra_phones": "+7 723 226-00-12",
        "instagram": "smiledent_ukk",
        "whatsapp": "+77232260011",
        "telegram": "smiledent_bot",
    },
]


def interactive_menu():
    """Интерактивный выбор параметров."""
    print("=" * 60)
    print("  FINVY B2B OUTREACH — Генератор персонализированных спитчей")
    print("=" * 60)

    # Выбор источника данных
    print("\n[DATA] Источник данных:")
    print("  1. Google Maps (нужен API ключ)")
    print("  2. Демо-данные (3 тестовых бизнеса)")
    source = input("\nВыбор [1/2]: ").strip()

    businesses = []

    if source == "1":
        queries_input = input("\nПоисковые запросы (через запятую, напр. 'кофейня, барбершоп'): ")
        queries = [q.strip() for q in queries_input.split(",") if q.strip()]
        if not queries:
            print("Не указаны запросы!")
            sys.exit(1)

        city = input(f"Город [{DEFAULT_CITY}]: ").strip() or DEFAULT_CITY

        # Парсинг
        businesses = parse_maps(queries, city)
        if not businesses:
            print("Бизнесы не найдены. Проверьте API ключ и запросы.")
            sys.exit(1)

        # Обогащение
        businesses = enrich_all(businesses)
    else:
        print("\n[Демо] Используем тестовые данные (3 бизнеса)")
        businesses = DEMO_BUSINESSES

    # Выбор сценария
    print("\n[SCENARIO] Сценарий:")
    for i, (key, val) in enumerate(SCENARIOS.items(), 1):
        print(f"  {i}. {val['name']}")
    print(f"  4. Все сценарии")
    sc_choice = input("\nВыбор [1-4]: ").strip()

    scenario_keys = list(SCENARIOS.keys())
    if sc_choice == "4":
        selected_scenarios = scenario_keys
    elif sc_choice in ("1", "2", "3"):
        selected_scenarios = [scenario_keys[int(sc_choice) - 1]]
    else:
        selected_scenarios = scenario_keys

    # Выбор канала
    print("\n[CHANNEL] Канал доставки:")
    for i, (key, val) in enumerate(CHANNELS.items(), 1):
        print(f"  {i}. {val['name']}")
    print(f"  4. Все каналы")
    ch_choice = input("\nВыбор [1-4]: ").strip()

    channel_keys = list(CHANNELS.keys())
    if ch_choice == "4":
        selected_channels = channel_keys
    elif ch_choice in ("1", "2", "3"):
        selected_channels = [channel_keys[int(ch_choice) - 1]]
    else:
        selected_channels = channel_keys

    return businesses, selected_scenarios, selected_channels


def save_to_csv(businesses: list[dict], filename: str):
    """Сохраняет результаты в CSV."""
    if not businesses:
        print("Нет данных для сохранения.")
        return

    fieldnames = [
        "name", "address", "rating", "reviews_count", "types",
        "phone", "website", "owner_name", "emails",
        "instagram", "whatsapp", "telegram",
        "reviews_sample", "scenario", "search_query",
    ]

    # Добавляем колонки спитчей динамически
    pitch_cols = [k for k in businesses[0].keys() if k.startswith("pitch_")]
    fieldnames.extend(pitch_cols)

    with open(filename, "w", newline="", encoding=OUTPUT_ENCODING) as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(businesses)

    print(f"\n[SAVE] Результаты сохранены: {filename}")
    print(f"   Бизнесов: {len(businesses)}")
    print(f"   Колонки спитчей: {', '.join(pitch_cols)}")


def main():
    parser = argparse.ArgumentParser(description="Finvy B2B Outreach Generator")
    parser.add_argument("--query", type=str, help="Поисковые запросы через запятую")
    parser.add_argument("--city", type=str, default=DEFAULT_CITY, help="Город")
    parser.add_argument("--scenario", type=str, choices=list(SCENARIOS.keys()) + ["all"], default="all")
    parser.add_argument("--channel", type=str, choices=list(CHANNELS.keys()) + ["all"], default="all")
    parser.add_argument("--demo", action="store_true", help="Использовать тестовые данные")
    parser.add_argument("--input", type=str, help="Путь к CSV с уже собранными бизнесами")
    parser.add_argument("--output", type=str, default=OUTPUT_CSV, help="Имя выходного CSV")
    args = parser.parse_args()

    # Если аргументы переданы — режим командной строки
    if args.query or args.demo or args.input:
        if args.demo:
            businesses = DEMO_BUSINESSES
        elif args.input:
            print(f"\n[DATA] Загружаем бизнесы из {args.input}...")
            businesses = []
            with open(args.input, "r", encoding=OUTPUT_ENCODING) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    businesses.append(row)
            print(f"   Загружено: {len(businesses)}")
        else:
            queries = [q.strip() for q in args.query.split(",")]
            businesses = parse_maps(queries, args.city)
            businesses = enrich_all(businesses)

        scenarios = list(SCENARIOS.keys()) if args.scenario == "all" else [args.scenario]
        channels = list(CHANNELS.keys()) if args.channel == "all" else [args.channel]
    else:
        # Интерактивный режим
        businesses, scenarios, channels = interactive_menu()

    # Генерация спитчей
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = args.output if (args.query or args.demo) else f"finvy_outreach_{timestamp}.csv"
    html_file = output_file.replace(".csv", ".html")

    for scenario in scenarios:
        for channel in channels:
            generate_all_pitches(businesses, scenario, channel)
            
            # Промежуточное сохранение
            save_to_csv(businesses, output_file)
            
            # Обновление HTML-отчета
            try:
                html_content = generate_html(output_file)
                with open(html_file, "w", encoding="utf-8") as f:
                    f.write(html_content)
                print(f"[AUTO-SAVE] Данные обновлены в {output_file} и {html_file}")
            except Exception as e:
                print(f"[WARN] Не удалось обновить HTML: {e}")

    # Финальное сообщение
    print("\n" + "=" * 60)
    print("  ГОТОВО! Результаты открыты в браузере.")
    print(f"  Файлы: {output_file}, {html_file}")
    print("=" * 60)
    
    # Автоматическое открытие (финальное)
    full_path = os.path.abspath(html_file)
    webbrowser.open(f"file:///{full_path}")


if __name__ == "__main__":
    main()
