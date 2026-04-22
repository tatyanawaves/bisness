"""
Генератор HTML-отчёта из CSV с результатами Finvy B2B Outreach.
Устойчивая версия: игнорирует битые строки, сохраняет оригинальный дизайн.
"""

import csv
import sys
import os
import webbrowser
from datetime import datetime


def generate_html(csv_file: str) -> str:
    # Устойчивое чтение данных (даже если CSV поврежден)
    rows = []
    try:
        with open(csv_file, 'r', encoding='utf-8-sig', errors='replace') as f:
            reader = csv.reader(f)
            header = next(reader)
            for row in reader:
                if not row: continue
                # Дополняем строку пустыми значениями, если колонок не хватает
                if len(row) < len(header):
                    row.extend([''] * (len(header) - len(row)))
                rows.append(dict(zip(header, row)))
    except Exception as e:
        print(f"Ошибка при чтении: {e}")
        sys.exit(1)

    if not rows:
        print("CSV пустой.")
        sys.exit(1)

    pitch_cols = [k for k in header if k and k.startswith("pitch_")]
    channel_labels = {
        "whatsapp": ("WhatsApp", "#25D366", "💬"),
        "email": ("Email", "#4285F4", "📧"),
        "cold_call": ("Холодный звонок", "#FF6B35", "📞"),
    }
    
    # Словари для маппинга сценариев (короткие метки)
    scenario_info = {
        "microbusiness": "Микро",
        "corporate_benefit": "Корп",
        "partner_network": "Партнёр",
    }

    cards_html = ""
    # Удаляем дубликаты по имени для чистоты отчета
    seen_names = set()
    unique_rows = []
    for r in rows:
        name = r.get("name", "").strip()
        if name and name not in seen_names:
            seen_names.add(name)
            unique_rows.append(r)

    for i, row in enumerate(unique_rows):
        rating_str = row.get("rating") or "0"
        try:
            rating = float(rating_str)
        except:
            rating = 0.0
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

        owner_html = f'<div class="meta-item"><span class="meta-label">Владелец</span><span class="meta-val">{owner}</span></div>' if owner else ""
        reviews_html = f'<div class="reviews-block"><span class="meta-label">Отзывы клиентов</span><p>"{reviews}"</p></div>' if reviews else ""

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
                {owner_html}
            </div>
            {reviews_html}
            <div class="tabs">
                <div class="tab-buttons">{tabs_buttons}</div>
                <div class="tab-content">{tabs_content}</div>
            </div>
        </div>'''

    generated_at = datetime.now().strftime("%d.%m.%Y %H:%M")

    return f'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Finvy Outreach — {len(unique_rows)} бизнесов</title>
<style>
  :root {{
    --bg: #0f1117;
    --card-bg: #1a1d27;
    --border: #2a2d3a;
    --text: #e8eaf0;
    --muted: #7b8098;
    --green: #00C896;
    --accent: #6c63ff;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 24px; }}

  .header {{ max-width: 900px; margin: 0 auto 32px; text-align: center; }}
  .header h1 {{ font-size: 24px; font-weight: 700; margin-bottom: 8px; }}
  .header h1 span {{ color: var(--green); }}
  .header .meta {{ color: var(--muted); font-size: 14px; }}

  .search-bar {{ max-width: 900px; margin: 0 auto 20px; }}
  .search-bar input {{ width: 100%; background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; padding: 12px 16px; color: var(--text); font-size: 14px; outline: none; }}
  .search-bar input:focus {{ border-color: var(--accent); }}

  .cards {{ max-width: 900px; margin: 0 auto; display: flex; flex-direction: column; gap: 20px; }}
  .card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 16px; overflow: hidden; transition: border-color .2s; }}
  .card:hover {{ border-color: #3a3d4a; }}

  .card-header {{ padding: 20px 24px 16px; display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 1px solid var(--border); }}
  .card-title-block {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
  .card-title-block h2 {{ font-size: 18px; font-weight: 700; }}
  .types-badge {{ background: rgba(108,99,255,.15); color: #a09af0; font-size: 11px; padding: 3px 10px; border-radius: 20px; border: 1px solid rgba(108,99,255,.3); }}
  .rating-block {{ text-align: right; }}
  .stars {{ color: #f5c518; font-size: 14px; letter-spacing: 1px; }}
  .rating-num {{ display: block; color: var(--muted); font-size: 12px; margin-top: 2px; }}

  .card-meta {{ padding: 16px 24px; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; border-bottom: 1px solid var(--border); }}
  .meta-item {{ display: flex; flex-direction: column; gap: 2px; }}
  .meta-label {{ font-size: 10px; text-transform: uppercase; color: var(--muted); letter-spacing: .5px; }}
  .meta-val {{ font-size: 13px; color: var(--text); }}
  .meta-val a {{ color: var(--green); text-decoration: none; }}

  .reviews-block {{ padding: 12px 24px; background: rgba(255,255,255,.02); border-bottom: 1px solid var(--border); }}
  .reviews-block p {{ font-size: 13px; color: var(--muted); font-style: italic; margin-top: 4px; }}

  .tabs {{ padding: 20px 24px; }}
  .tab-buttons {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }}
  .tab-btn {{ background: transparent; border: 1px solid var(--border); color: var(--muted); padding: 7px 14px; border-radius: 8px; font-size: 13px; cursor: pointer; }}
  .tab-btn.active {{ background: var(--accent); border-color: var(--accent); color: #fff; }}

  .tab-pane {{ display: none; }}
  .tab-pane.active {{ display: block; }}
  .pitch-text {{ font-size: 14px; line-height: 1.7; color: #c8cad8; background: rgba(0,0,0,.2); border-radius: 10px; padding: 16px; border-left: 3px solid var(--accent); }}

  .copy-btn {{ margin-top: 12px; background: transparent; border: 1px solid var(--border); color: var(--muted); padding: 7px 16px; border-radius: 8px; font-size: 12px; cursor: pointer; }}
  .copy-btn:hover {{ border-color: var(--green); color: var(--green); }}

  .hidden {{ display: none !important; }}
</style>
</head>
<body>

<div class="header">
    <h1>Finvy <span>B2B</span> Outreach</h1>
    <div class="meta">Найдено {len(unique_rows)} бизнесов • Обновлено {generated_at}</div>
</div>

<div class="search-bar">
  <input type="text" placeholder="Поиск по названию или адресу..." oninput="filterCards(this.value)">
</div>

<div class="cards" id="cards-container">
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

if __name__ == "__main__":
    csv_file = sys.argv[1] if len(sys.argv) > 1 else "finvy_outreach_results.csv"
    output_html = "finvy_outreach_results.html"
    html = generate_html(csv_file)
    with open(output_html, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML обновлен: {output_html}")
    webbrowser.open(f"file:///{os.path.abspath(output_html)}")
