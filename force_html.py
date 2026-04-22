import csv
import sys
import os
import webbrowser
from datetime import datetime

# Копия логики из export_html.py, но с защитой от битых CSV
def generate_html_robust(csv_file: str) -> str:
    rows = []
    # Используем 'replace' для обработки возможных битых байтов
    with open(csv_file, 'r', encoding='utf-8-sig', errors='replace') as f:
        # Читаем через csv.reader, так как он более устойчив к битым строкам, чем DictReader
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return "<h1>CSV пустой</h1>"
            
        for row in reader:
            if not row: continue
            # Если в строке меньше колонок, чем в заголовке, дополняем пустыми
            if len(row) < len(header):
                row.extend([''] * (len(header) - len(row)))
            # Создаем словарь для удобства
            rows.append(dict(zip(header, row)))

    if not rows:
        return "<h1>Нет данных для отображения</h1>"

    pitch_cols = [k for k in header if k and k.startswith("pitch_")]
    
    channel_info = {
        "whatsapp": ("WhatsApp", "#25D366", "💬"),
        "email": ("Email", "#4285F4", "📧"),
        "cold_call": ("Звонок", "#FF6B35", "📞"),
    }
    
    scenario_info = {
        "microbusiness": "Микро",
        "corporate_benefit": "Корп",
        "partner_network": "Партнёр",
    }

    cards_html = ""
    # Удаляем дубликаты по имени, чтобы отчет был чище
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
        
        active_pitches = [pc for pc in pitch_cols if row.get(pc)]
        
        for j, col in enumerate(active_pitches):
            parts = col.split("_")
            if len(parts) >= 3:
                sc_id = "_".join(parts[1:-1])
                ch_id = parts[-1]
            else:
                sc_id = ""
                ch_id = parts[-1]
                
            ch_name, color, icon = channel_info.get(ch_id, (ch_id.capitalize(), "#888", ""))
            sc_label = f" ({scenario_info.get(sc_id, sc_id)})" if sc_id else ""
            label = f"{icon} {ch_name}{sc_label}"
            
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
        <div class="card">
            <div class="card-header">
                <div>
                    <h2>{row.get("name", "Без названия")}</h2>
                    <span class="types-badge">{row.get("search_query", row.get("types",""))}</span>
                </div>
                <div style="text-align:right">
                    <span style="color:#f5c518">{stars}</span>
                    <div style="color:#7b8098;font-size:12px">{rating} ({row.get("reviews_count", 0)} отз.)</div>
                </div>
            </div>
            <div class="card-meta" style="padding:15px 24px; display:grid; grid-template-columns: 1fr 1fr; gap:10px; border-bottom:1px solid #2a2d3a">
                <div><small style="color:#7b8098">АДРЕС</small><br>{row.get("address","—")}</div>
                <div><small style="color:#7b8098">ТЕЛЕФОН</small><br>{phone}</div>
                <div><small style="color:#7b8098">EMAIL</small><br>{email}</div>
                <div><small style="color:#7b8098">САЙТ</small><br>{website_html}</div>
            </div>
            <div class="tabs" style="padding:20px 24px">
                <div class="tab-buttons" style="display:flex; gap:10px; margin-bottom:15px">{tabs_buttons}</div>
                <div class="tab-content">{tabs_content}</div>
            </div>
        </div>'''

    generated_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    
    # CSS и HTML структура
    html_template = f'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Finvy Outreach — {len(unique_rows)} бизнесов</title>
<style>
  body {{ background: #0f1117; color: #e8eaf0; font-family: sans-serif; padding: 40px; }}
  .card {{ background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 12px; margin-bottom: 24px; max-width: 900px; margin-left: auto; margin-right: auto; overflow: hidden; }}
  .card-header {{ padding: 20px 24px; display: flex; justify-content: space-between; border-bottom: 1px solid #2a2d3a; }}
  .types-badge {{ background: rgba(108,99,255,0.1); color: #a09af0; font-size: 11px; padding: 3px 8px; border-radius: 4px; }}
  .tab-btn {{ background: none; border: 1px solid #2a2d3a; color: #7b8098; padding: 8px 16px; border-radius: 6px; cursor: pointer; }}
  .tab-btn.active {{ background: #6c63ff; color: #fff; border-color: #6c63ff; }}
  .tab-pane {{ display: none; }}
  .tab-pane.active {{ display: block; }}
  .pitch-text {{ background: #000; padding: 15px; border-radius: 8px; font-size: 14px; line-height: 1.6; border-left: 4px solid #6c63ff; }}
  .copy-btn {{ margin-top: 10px; background: none; border: 1px solid #2a2d3a; color: #7b8098; padding: 5px 10px; cursor: pointer; border-radius: 4px; }}
</style>
</head>
<body>
<h1 style="text-align:center; margin-bottom:40px">Finvy Outreach — Найдено {len(unique_rows)} бизнесов</h1>
{cards_html}
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
</script>
</body>
</html>'''
    return html_template

if __name__ == "__main__":
    csv_file = "finvy_outreach_results.csv"
    output_html = "finvy_outreach_results.html"
    html = generate_html_robust(csv_file)
    with open(output_html, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML обновлен: {output_html}")
    webbrowser.open(f"file:///{os.path.abspath(output_html)}")
