import csv
import glob
import os
import webbrowser
from datetime import datetime

def merge_all_outreach_data():
    all_businesses = {} # Ключ - название бизнеса (нормализованное)
    csv_files = glob.glob("*.csv")
    
    print(f"Найдено {len(csv_files)} CSV файлов для анализа.")
    
    for filename in csv_files:
        print(f"Анализирую {filename}...", end=" ")
        count = 0
        try:
            with open(filename, 'r', encoding='utf-8-sig', errors='replace') as f:
                reader = csv.reader(f)
                header = next(reader)
                
                # Приводим заголовки к нижнему регистру для надежности
                header = [h.strip().lower() for h in header]
                
                for row in reader:
                    if not row: continue
                    if len(row) < 2: continue # Пропускаем пустые или битые строки
                    
                    # Создаем временный словарь для строки
                    data = dict(zip(header, row))
                    name = data.get("name", "").strip()
                    if not name: continue
                    
                    # Если бизнес уже есть, объединяем данные
                    if name not in all_businesses:
                        all_businesses[name] = data
                    else:
                        # Дополняем недостающие данные (телефон, почту, спитчи)
                        for k, v in data.items():
                            if v and not all_businesses[name].get(k):
                                all_businesses[name][k] = v
                    count += 1
            print(f"OK ({count} строк)")
        except Exception as e:
            print(f"Ошибка в {filename}: {e}")

    # Собираем список всех колонок спитчей из всех файлов
    all_pitch_cols = set()
    for biz in all_businesses.values():
        for k in biz.keys():
            if k.startswith("pitch_") and biz[k]:
                all_pitch_cols.add(k)
    
    return list(all_businesses.values()), sorted(list(all_pitch_cols))

def generate_master_html(businesses, pitch_cols):
    channel_labels = {
        "whatsapp": ("WhatsApp", "#25D366", "💬"),
        "email": ("Email", "#4285F4", "📧"),
        "cold_call": ("Холодный звонок", "#FF6B35", "📞"),
    }
    
    scenario_info = {
        "microbusiness": "Микро",
        "corporate_benefit": "Корп",
        "partner_network": "Партнёр",
    }

    cards_html = ""
    for i, row in enumerate(businesses):
        rating_str = row.get("rating") or "0"
        try: rating = float(rating_str)
        except: rating = 0.0
        stars = "★" * int(rating) + "☆" * (5 - int(rating))

        phone = row.get("phone") or row.get("extra_phones") or "—"
        email = row.get("emails") or "—"
        website = row.get("website") or ""
        instagram = row.get("instagram") or ""
        owner = row.get("owner_name") or ""
        reviews = row.get("reviews_sample") or ""

        website_html = f'<a href="{website}" target="_blank">{website}</a>' if website else "—"
        instagram_html = f'<a href="https://instagram.com/{instagram}" target="_blank">@{instagram}</a>' if instagram else "—"

        tabs_buttons = ""
        tabs_content = ""
        
        # Показываем только те вкладки, где есть сгенерированный текст
        active_pitches = [pc for pc in pitch_cols if row.get(pc)]
        
        for j, col in enumerate(active_pitches):
            parts = col.split("_")
            if len(parts) >= 3:
                sc_id = "_".join(parts[1:-1])
                ch_id = parts[-1]
            else:
                sc_id = ""
                ch_id = parts[-1]
            
            label_info, color, icon = channel_labels.get(ch_id, (ch_id.capitalize(), "#888", "📄"))
            sc_label = f" ({scenario_info.get(sc_id, sc_id)})" if sc_id else ""
            label = f"{icon} {label_info}{sc_label}"
            
            active_btn = "active" if j == 0 else ""
            active_pane = "active" if j == 0 else ""
            tabs_buttons += f'<button class="tab-btn {active_btn}" onclick="switchTab(this, \'card{i}-{col}\')" style="--accent:{color}">{label}</button>\n'

            pitch_text = row.get(col) or ""
            pitch_formatted = pitch_text.replace("\n", "<br>")

            tabs_content += f'''
            <div class="tab-pane {active_pane}" id="card{i}-{col}">
                <div class="pitch-text">{pitch_formatted}</div>
                <button class="copy-btn" onclick="copyText(this)" data-text="{pitch_text.replace('"', '&quot;')}">Скопировать</button>
            </div>'''

        cards_html += f'''
        <div class="card" id="card-{i}">
            <div class="card-header">
                <div class="card-title-block">
                    <h2>{row.get("name", "Без названия")}</h2>
                    <span class="types-badge">{row.get("search_query", row.get("types","")).split(",")[0].strip()}</span>
                </div>
                <div class="rating-block">
                    <span class="stars">{stars}</span>
                    <span class="rating-num">{rating} ({row.get("reviews_count", 0)} отз.)</span>
                </div>
            </div>
            <div class="card-meta">
                <div class="meta-item"><span class="meta-label">Адрес</span><span class="meta-val">{row.get("address","—")}</span></div>
                <div class="meta-item"><span class="meta-label">Телефон</span><span class="meta-val">{phone}</span></div>
                <div class="meta-item"><span class="meta-label">Email</span><span class="meta-val">{email}</span></div>
                <div class="meta-item"><span class="meta-label">Сайт</span><span class="meta-val">{website_html}</span></div>
                <div class="meta-item"><span class="meta-label">Instagram</span><span class="meta-val">{instagram_html}</span></div>
                <div class="meta-item"><span class="meta-label">Владелец</span><span class="meta-val">{owner or "—"}</span></div>
            </div>
            <div class="reviews-block" style="padding:12px 24px; background:rgba(255,255,255,0.02); border-bottom:1px solid #2a2d3a">
                <span class="meta-label">Отзывы клиентов</span>
                <p style="font-size:13px; color:#7b8098; font-style:italic; margin-top:4px">"{reviews or "Нет данных по отзывам"}"</p>
            </div>
            <div class="tabs" style="padding:20px 24px">
                <div class="tab-buttons" style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:16px">{tabs_buttons}</div>
                <div class="tab-content">{tabs_content}</div>
            </div>
        </div>'''

    generated_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    
    html_template = f'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Finvy Master Outreach — {len(businesses)} бизнесов</title>
<style>
  :root {{ --bg: #0f1117; --card-bg: #1a1d27; --border: #2a2d3a; --text: #e8eaf0; --muted: #7b8098; --green: #00C896; --accent: #6c63ff; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: sans-serif; padding: 24px; }}
  .header {{ max-width: 900px; margin: 0 auto 32px; text-align: center; border-bottom: 2px solid var(--border); padding-bottom: 20px; }}
  .header h1 {{ font-size: 28px; margin-bottom: 8px; }}
  .header span {{ color: var(--green); }}
  .search-bar {{ max-width: 900px; margin: 0 auto 24px; }}
  .search-bar input {{ width: 100%; background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 14px 20px; color: var(--text); outline: none; }}
  .search-bar input:focus {{ border-color: var(--accent); }}
  .cards {{ max-width: 900px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px; }}
  .card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 20px; overflow: hidden; }}
  .card-header {{ padding: 24px; display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 1px solid var(--border); }}
  .card-title-block h2 {{ font-size: 20px; }}
  .types-badge {{ background: rgba(108,99,255,0.15); color: #a09af0; font-size: 11px; padding: 4px 12px; border-radius: 20px; margin-top: 8px; display: inline-block; }}
  .rating-block {{ text-align: right; }}
  .stars {{ color: #f5c518; }}
  .card-meta {{ padding: 20px 24px; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; border-bottom: 1px solid var(--border); }}
  .meta-label {{ font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }}
  .meta-val {{ font-size: 13px; margin-top: 2px; }}
  .meta-val a {{ color: var(--green); text-decoration: none; }}
  .tab-btn {{ background: transparent; border: 1px solid var(--border); color: var(--muted); padding: 8px 16px; border-radius: 10px; cursor: pointer; }}
  .tab-btn.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
  .tab-pane {{ display: none; padding-top: 10px; }}
  .tab-pane.active {{ display: block; }}
  .pitch-text {{ background: rgba(0,0,0,0.3); padding: 20px; border-radius: 12px; font-size: 14px; line-height: 1.8; border-left: 4px solid var(--accent); }}
  .copy-btn {{ margin-top: 15px; background: transparent; border: 1px solid var(--border); color: var(--muted); padding: 8px 16px; border-radius: 8px; cursor: pointer; }}
  .hidden {{ display: none !important; }}
</style>
</head>
<body>
<div class="header">
    <h1>Finvy <span>Master</span> Outreach Report</h1>
    <div style="color:var(--muted)">Собрано из всех CSV-файлов • {len(businesses)} уникальных компаний</div>
</div>
<div class="search-bar">
    <input type="text" placeholder="Поиск по всей базе..." oninput="filterCards(this.value)">
</div>
<div class="cards">
{cards_html}
</div>
<script>
function switchTab(btn, paneId) {{
  const card = btn.closest('.card');
  card.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  card.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById(paneId).classList.add('active');
}}
function copyText(btn) {{
  const text = btn.getAttribute('data-text');
  navigator.clipboard.writeText(text).then(() => {{
    const old = btn.innerText; btn.innerText = 'Скопировано!';
    setTimeout(() => btn.innerText = old, 2000);
  }});
}}
function filterCards(query) {{
  const q = query.toLowerCase();
  document.querySelectorAll('.card').forEach(card => {{
    const text = card.innerText.toLowerCase();
    card.classList.toggle('hidden', q.length > 0 && !text.includes(q));
  }});
}}
</script>
</body>
</html>'''
    return html_template

if __name__ == "__main__":
    businesses, pitch_cols = merge_all_outreach_data()
    print(f"Итого уникальных бизнесов: {len(businesses)}")
    print(f"Обнаружено колонок со спитчами: {len(pitch_cols)}")
    
    html = generate_master_html(businesses, pitch_cols)
    with open("finvy_master_report.html", "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"Мастер-отчет создан: finvy_master_report.html")
    webbrowser.open(f"file:///{os.path.abspath('finvy_master_report.html')}")
