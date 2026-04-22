import os
import csv
from flask import Flask, request, jsonify, render_template
from config import OUTPUT_CSV, DEFAULT_CITY, OUTPUT_ENCODING
from maps_parser import parse_maps
from enricher import enrich_all
from pitch_generator import generate_pitch, SCENARIOS, CHANNELS

app = Flask(__name__)

def load_csv(filename):
    businesses = []
    if os.path.exists(filename):
        with open(filename, "r", encoding=OUTPUT_ENCODING, errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                businesses.append(row)
    return businesses

def save_csv(businesses, filename):
    if not businesses: return
    # Collect all fieldnames
    fieldnames = set()
    for b in businesses:
        fieldnames.update(b.keys())
    
    # Ensure standard order and dynamic pitches at the end
    base_fields = [
        "place_id", "name", "address", "rating", "reviews_count", "types", "business_status",
        "phone", "website", "google_maps_url", "reviews_sample", "search_query",
        "owner_name", "emails", "extra_phones", "instagram", "whatsapp", "telegram",
        "last_scenario", "last_channel"
    ]
    final_fields = [f for f in base_fields if f in fieldnames] + [f for f in fieldnames if f not in base_fields]

    with open(filename, "w", newline="", encoding=OUTPUT_ENCODING) as f:
        writer = csv.DictWriter(f, fieldnames=final_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(businesses)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/businesses", methods=["GET"])
def get_businesses():
    """Возвращает бизнесы с готовыми спитчами при загрузке."""
    businesses = load_csv(OUTPUT_CSV)
    return jsonify({"businesses": businesses})

@app.route("/api/parse", methods=["POST"])
def parse():
    """Сбор информации и номеров (парсинг + обогащение)"""
    data = request.json
    queries = [q.strip() for q in data.get("category", "").split(",") if q.strip()]
    city = data.get("city", DEFAULT_CITY)
    if not queries:
        return jsonify({"error": "Категория не указана"}), 400
    
    try:
        new_businesses = parse_maps(queries, city)
        if not new_businesses:
            return jsonify({"error": "Ничего не найдено"}), 404
            
        new_businesses = enrich_all(new_businesses)
        
        # Merge this with existing
        existing = load_csv(OUTPUT_CSV)
        existing_map = {b.get("place_id", b.get("name")): b for b in existing}
        
        for nb in new_businesses:
            key = nb.get("place_id", nb.get("name"))
            if key in existing_map:
                # Update but preserve pitches
                for pk, pv in existing_map[key].items():
                    if pk.startswith("pitch_") and pk not in nb:
                        nb[pk] = pv
            existing_map[key] = nb
        
        updated_list = list(existing_map.values())
        save_csv(updated_list, OUTPUT_CSV)
        
        return jsonify({"businesses": new_businesses, "total": len(updated_list)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/scenarios", methods=["GET"])
def get_scenarios():
    return jsonify({"scenarios": SCENARIOS, "channels": CHANNELS})

@app.route("/api/generate_single", methods=["POST"])
def generate_single():
    """Генерирует спитч для одной компании"""
    data = request.json
    b = data.get("business")
    scenario = data.get("scenario", "b2b_sales")
    channel = data.get("channel", "whatsapp")
    
    if not b:
        return jsonify({"error": "No business provided"}), 400
        
    pitch = generate_pitch(b, scenario, channel)
    pitch_key = f"pitch_{scenario}_{channel}"
    b[pitch_key] = pitch
    b["last_scenario"] = SCENARIOS.get(scenario, {}).get("name", scenario)
    b["last_channel"] = CHANNELS.get(channel, {}).get("name", channel)
    
    existing = load_csv(OUTPUT_CSV)
    updated = False
    for i, ex_b in enumerate(existing):
        if ex_b.get("place_id") == b.get("place_id", "") or ex_b.get("name") == b.get("name"):
            existing[i].update(b)
            updated = True
            break
            
    if not updated:
        existing.append(b)
        
    save_csv(existing, OUTPUT_CSV)
    
    return jsonify({
        "business": b,
        "pitch": pitch,
        "pitch_key": pitch_key
    })

@app.route("/api/clear_pitches", methods=["POST"])
def clear_pitches():
    """Очищает выбранный спитч для одной компании"""
    data = request.json
    business_id = data.get("business_id")
    scenario = data.get("scenario", "finvy_main")
    channel = data.get("channel", "all")
    
    if not business_id:
        return jsonify({"error": "No business provided"}), 400
        
    existing = load_csv(OUTPUT_CSV)
    updated_biz = None
    for i, ex_b in enumerate(existing):
        if ex_b.get("place_id") == business_id or ex_b.get("name") == business_id:
            if channel == "all":
                # Очищаем все спитчи
                for k in list(ex_b.keys()):
                    if k.startswith("pitch_"):
                        ex_b[k] = ""
            else:
                pitch_key = f"pitch_{scenario}_{channel}"
                ex_b[pitch_key] = ""
            updated_biz = ex_b
            break
            
    if updated_biz:
        save_csv(existing, OUTPUT_CSV)
        return jsonify({"success": True, "business": updated_biz})
    else:
        return jsonify({"error": "Not found"}), 404

if __name__ == "__main__":
    # Create templates directory if not exists
    os.makedirs("templates", exist_ok=True)
    app.run(debug=True, port=5000)
