import csv
import os
import sys
import time
from pitch_generator import generate_pitch, SCENARIOS, CHANNELS

# Mapping from Russian scenario names to internal keys
SCENARIO_MAP = {
    "Микробизнес — Разделение потоков": "microbusiness",
    "Корпоративный бенефит для сотрудников": "corporate_benefit",
    "Партнёрская сеть — кешбэк и акции": "partner_network",
}

def clean_pitch(text):
    if not text:
        return ""
    if "[ERROR:" in str(text) or "[ОШИБКА" in str(text) or "rate limit" in str(text).lower():
        return ""
    return str(text).strip()

def main():
    files = ["finvy_FULL_outreach.csv", "finvy_outreach_results.csv", "finvy_test_5.csv"]
    businesses = {}
    
    standard_pitch_cols = []
    for s in SCENARIOS.keys():
        for c in CHANNELS.keys():
            standard_pitch_cols.append(f"pitch_{s}_{c}")

    all_headers = set()

    for f in files:
        if os.path.exists(f):
            print(f"Reading {f}...")
            try:
                with open(f, mode='r', encoding='utf-8-sig') as csvfile:
                    reader = csv.DictReader(csvfile)
                    all_headers.update(reader.fieldnames)
                    for row in reader:
                        name = row.get('name', '').strip()
                        if not name:
                            continue
                        
                        # Initialize business record if not exists
                        if name not in businesses:
                            businesses[name] = {}
                        
                        # Update business record with non-empty values
                        for key, value in row.items():
                            if value and (key not in businesses[name] or not businesses[name][key]):
                                businesses[name][key] = value
                        
                        # Map scenario-specific pitches if scenario is present
                        sc_val = row.get('scenario')
                        sc_key = SCENARIO_MAP.get(sc_val)
                        if sc_key:
                            for ch_key in CHANNELS.keys():
                                # Try to find pitch_whatsapp, pitch_email, pitch_cold_call
                                old_col = f"pitch_{ch_key}"
                                new_col = f"pitch_{sc_key}_{ch_key}"
                                if old_col in row and row[old_col]:
                                    val = clean_pitch(row[old_col])
                                    if val and (new_col not in businesses[name] or not businesses[name][new_col]):
                                        businesses[name][new_col] = val
            except Exception as e:
                print(f"Error reading {f}: {e}")
        else:
            print(f"Warning: {f} not found.")

    if not businesses:
        print("No business data found.")
        return

    # Add standard pitch columns to headers
    all_headers.update(standard_pitch_cols)
    
    # Sort headers to have a consistent output
    sorted_headers = sorted(list(all_headers))
    # Move 'name' to the front
    if 'name' in sorted_headers:
        sorted_headers.remove('name')
        sorted_headers = ['name'] + sorted_headers

    print(f"Total unique businesses: {len(businesses)}")
    
    # Clean existing pitches in businesses
    for name, biz in businesses.items():
        for col in standard_pitch_cols:
            if col in biz:
                biz[col] = clean_pitch(biz[col])
            else:
                biz[col] = ""

    # Identify missing pitches
    to_generate = []
    for name, biz in businesses.items():
        for sc_key in SCENARIOS.keys():
            for ch_key in CHANNELS.keys():
                col = f"pitch_{sc_key}_{ch_key}"
                if not biz.get(col):
                    to_generate.append((name, col, sc_key, ch_key))

    print(f"Need to generate {len(to_generate)} pitches.")
    
    # Limitation: if there are TOO many, we might hit Groq limits quickly.
    # The user said "read all CSV... generate... save... run export".
    # I'll try to generate as many as possible.
    
    count = 0
    for name, col, sc_key, ch_key in to_generate:
        count += 1
        print(f"[{count}/{len(to_generate)}] Generating {col} for {name}...")
        
        pitch = generate_pitch(businesses[name], sc_key, ch_key)
        
        if "rate limit" in pitch.lower() or "429" in pitch:
            print(f"  FAILED (Rate Limit). Stopping generation.")
            businesses[name][col] = pitch
            break
        
        businesses[name][col] = pitch
        print("  OK")
        time.sleep(1) # Small delay to avoid hitting rate limits too fast

    # Save to CSV
    output_file = "finvy_perfect_outreach.csv"
    try:
        with open(output_file, mode='w', encoding='utf-8-sig', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=sorted_headers)
            writer.writeheader()
            for name in sorted(businesses.keys()):
                row = businesses[name]
                # Ensure all headers are present in row
                row_to_write = {h: row.get(h, "") for h in sorted_headers}
                writer.writerow(row_to_write)
        print(f"Saved to {output_file}")
    except Exception as e:
        print(f"Error saving {output_file}: {e}")

if __name__ == "__main__":
    main()
