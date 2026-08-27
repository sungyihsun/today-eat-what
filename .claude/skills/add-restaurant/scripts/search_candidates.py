# -*- coding: utf-8 -*-
"""
Template: search Google Places (New) Text Search for restaurant candidates.

EDIT PER TASK before running:
  - GOOGLE_PLACES_API_KEY: API key from the environment (or KEY_PATH for local use)
  - AREAS: {label: (lat, lng)} for each area the user asked for
  - QUERIES: {label: [query strings]} — 3-5 phrasings per area works well;
    one query alone tends to miss real candidates
  - MIN_RATING / MIN_REVIEWS: adjust if the category is niche (fewer reviews
    available) or if the user wants only very well-established places
  - OUT_PATH: where to write the candidates JSON

Usage: python3 search_candidates.py
"""
import json, os, urllib.request, urllib.error, time, re

SB = os.environ.get("ADD_RESTAURANT_SCRATCHPAD", "<YOUR_SCRATCHPAD_DIR>")
KEY_PATH = f"{SB}/gmaps_key.txt"
OUT_PATH = os.environ.get("ADD_RESTAURANT_CANDIDATES_PATH", f"{SB}/candidates.json")

MIN_RATING = 4.0
MIN_REVIEWS = 15

# EDIT: area label -> (lat, lng) center for locationBias
AREAS = {
    "新竹市": (24.8055, 120.9686),
    "竹北": (24.8339, 121.0085),
    "中壢": (24.9535, 121.2251),
    "青埔": (25.0170, 121.2136),
}

# EDIT: area label -> list of query strings to try for that area
QUERIES = {
    "新竹市": ["健康餐 新竹市", "輕食 新竹市"],
    "竹北": ["健康餐 竹北", "輕食 竹北"],
}

KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
if not KEY and SB != "<YOUR_SCRATCHPAD_DIR>":
    with open(KEY_PATH, encoding="utf-8") as key_file:
        KEY = key_file.read().strip()
if not KEY:
    raise SystemExit("Missing GOOGLE_PLACES_API_KEY or local scratchpad key file")

def search_text(query, lat, lng, radius=8000.0):
    url = "https://places.googleapis.com/v1/places:searchText"
    body = json.dumps({
        "textQuery": query, "languageCode": "zh-TW",
        "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius}}
    }).encode('utf-8')
    field_mask = ("places.id,places.displayName,places.formattedAddress,places.rating,"
                  "places.userRatingCount,places.priceLevel,places.googleMapsUri,"
                  "places.location,places.types")
    req = urllib.request.Request(url, data=body, method='POST', headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": KEY, "X-Goog-FieldMask": field_mask,
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode('utf-8')}

all_results = {}
for area_label, queries in QUERIES.items():
    lat, lng = AREAS[area_label]
    for q in queries:
        data = search_text(q, lat, lng)
        places = data.get('places', [])
        print(f"{q}: {len(places)} results", flush=True)
        for p in places:
            cid_m = re.search(r'cid=(\d+)', p.get('googleMapsUri', ''))
            cid = cid_m.group(1) if cid_m else None
            if not cid:
                continue
            rating = p.get('rating', 0)
            count = p.get('userRatingCount', 0)
            if rating < MIN_RATING or count < MIN_REVIEWS:
                continue
            all_results[cid] = {
                'place_id': p.get('id'),
                'name': p.get('displayName', {}).get('text', ''),
                'address': p.get('formattedAddress', ''),
                'rating': rating,
                'userRatingCount': count,
                'priceLevel': p.get('priceLevel'),
                'googleMapsUri': p.get('googleMapsUri'),
                'location': p.get('location'),
                'types': p.get('types'),
                'area_label': area_label,
            }
        time.sleep(0.15)

print("total unique candidates:", len(all_results))
json.dump(all_results, open(OUT_PATH, 'w'), ensure_ascii=False, indent=1)

for area_label in QUERIES:
    print(f"--- {area_label} ---")
    for cid, v in sorted(all_results.items(), key=lambda x: -x[1]['rating']):
        if v['area_label'] == area_label:
            print(f"{v['rating']:.1f} ({v['userRatingCount']:>5}) {v['name']} | {v['address']} | types={v['types']}")
