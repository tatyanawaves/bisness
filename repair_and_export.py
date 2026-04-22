import csv
import glob
import os
import webbrowser
from datetime import datetime

# 1. СБОР И ОБЪЕДИНЕНИЕ ДАННЫХ
def repair_data():
    all_businesses = {}
    csv_files = ["finvy_FULL_outreach.csv", "finvy_outreach_results.csv", "finvy_test_5.csv"]
    
    print("Начинаю сбор данных из всех файлов...")
    
    for filename in csv_files:
        if not os.path.exists(filename): continue
        print(f"Обработка {filename}...")
        try:
            with open(filename, 'r', encoding='utf-8-sig', errors='replace') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get("name")
                    if not name: continue
                    if name not in all_businesses:
                        all_businesses[name] = row
                    else:
                        for k, v in row.items():
                            if v and (not all_businesses[name].get(k) or "429" in str(all_businesses[name].get(k))):
                                all_businesses[name][k] = v
        except Exception as e:
            print(f"Ошибка в {filename}: {e}")

    # 2. ИСПРАВЛЕНИЕ ОШИБОК 429 (Генерация качественных спитчей)
    print("Исправление ошибок генерации (429)...")
    
    pitch_cols = [k for k in next(iter(all_businesses.values())).keys() if k.startswith("pitch_")]
    
    for name, biz in all_businesses.items():
        rating = biz.get("rating", "4.0")
        reviews = biz.get("reviews_sample", "")
        
        for col in pitch_cols:
            text = biz.get(col, "")
            if "429" in str(text) or not str(text).strip():
                # Умная замена в зависимости от канала и сценария
                if "whatsapp" in col:
                    if "micro" in col:
                        biz[col] = f"Привет, {name}! ☕️ Видел ваши отзывы: '{reviews[:50]}...'. Мы в Finvy помогаем владельцам разделять личные деньги и выручку, чтобы видеть чистую прибыль без бухгалтера. Интересно попробовать? ✅"
                    elif "partner" in col:
                        biz[col] = f"Добрый день! 🤝 Хотим добавить {name} в нашу партнерскую сеть кешбэка. У нас активная база пользователей, которые ищут такие места. Вам нужны новые клиенты без затрат на рекламу? 😊"
                    else:
                        biz[col] = f"Здравствуйте! Предлагаем {name} корпоративный доступ к Finvy для сотрудников. Это снижает их финансовый стресс и повышает лояльность к компании. Хотите короткое демо? 🚀"
                
                elif "email" in col:
                    biz[col] = f"Тема: Развитие {name} через финтех-инструменты\n\nЗдравствуйте!\n\nМы проанализировали работу {name} и видим большой потенциал для оптимизации через Finvy. Наше решение позволяет эффективно управлять финансовыми потоками и привлекать новую аудиторию через систему кешбэка.\n\nГотовы обсудить подробности?\n\nС уважением, команда Finvy."
                
                else: # cold_call
                    biz[col] = f"Скрипт для {name}:\n1. Зацепка: 'Видел ваш высокий рейтинг {rating}, отличная работа!'\n2. Боль: 'Многие владельцы тратят часы на учет личных и бизнес-денег.'\n3. Решение: 'Finvy делает это за 5 минут в день.'\n4. Закрытие: 'Давайте встретимся на 10 минут во вторник?'"

    # Сохраняем в финальный CSV
    # Собираем ВСЕ уникальные заголовки изо всех объектов
    all_fields = set()
    for biz in all_businesses.values():
        all_fields.update(biz.keys())
    
    fieldnames = sorted(list(all_fields))
    
    with open('finvy_REPAIRED_outreach.csv', 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(all_businesses.values())
    
    return "finvy_REPAIRED_outreach.csv"

if __name__ == "__main__":
    final_csv = repair_data()
    print(f"База исправлена и сохранена в {final_csv}")
    
    # Теперь вызываем генератор HTML
    from export_html import generate_html
    html_content = generate_html(final_csv)
    with open("finvy_final_report.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print("Финальный HTML-отчет готов: finvy_final_report.html")
    webbrowser.open(f"file:///{os.path.abspath('finvy_final_report.html')}")
