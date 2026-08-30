# -*- coding: utf-8 -*-
"""
One-off: search Google Places for Taiwan (新竹市/竹北/桃園) clothing-store
candidates, split into 5 categories (男裝/女裝/鞋包配件/平價/選品), for the
new "服飾" entry point in the local (non-trip) version of the site. Mirrors
scripts/busan-trip/search_busan_categories.py's hub-based, category-first
search pattern, but adds back the Taiwan pipeline's AREA_KEYWORDS address
safeguard (from .claude/skills/add-restaurant/scripts/search_candidates.py)
since these results DO need a real 新竹市/竹北/桃園 area assignment, unlike
the Busan trip data.

Usage (CI): GOOGLE_PLACES_API_KEY=... python3 scripts/taiwan-clothing/search_clothing_categories.py
"""
import json, os, urllib.request, urllib.error, time, re

OUT_PATH = os.environ.get("TW_CLOTHING_CANDIDATES_PATH", "candidate-results/tw-clothing-candidates.json")

MIN_RATING = 4.0
# Small boutiques collect far fewer reviews than restaurants.
MIN_REVIEWS = 10

KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
if not KEY:
    raise SystemExit("Missing GOOGLE_PLACES_API_KEY")

# Hub points, same centers as the Taiwan food search pipeline.
HUBS = {
    "新竹市": (24.8055, 120.9686),
    "竹北": (24.8339, 121.0085),
    "桃園": (25.0000, 121.3009),
}

# area label -> substring(s) that must appear in formattedAddress to accept
# a candidate under that area (locationBias only biases, doesn't guarantee).
AREA_KEYWORDS = {
    "新竹市": ["新竹市"],
    "竹北": ["竹北市"],
    "桃園": ["桃園市", "桃园市"],
}

# detail-cat label -> query strings to try at every hub above.
CATEGORY_QUERIES = {
    "男裝": ["男裝店", "男生服飾店", "型男服飾"],
    "女裝": ["女裝店", "女生服飾店", "韓系女裝"],
    "鞋包配件": ["鞋店", "包包配件店", "飾品配件店"],
    "平價服飾": ["平價服飾店", "均一價服飾", "outlet 服飾"],
    "選品店": ["選品店", "編輯選物店", "設計師選品"],
}


def search_text(query, lat, lng, radius=6000.0):
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
for cat_label, queries in CATEGORY_QUERIES.items():
    for q in queries:
        for hub_label, (lat, lng) in HUBS.items():
            data = search_text(f"{hub_label} {q}", lat, lng)
            places = data.get('places', [])
            print(f"{cat_label} / {q} @ {hub_label}: {len(places)} results", flush=True)
            for p in places:
                cid_m = re.search(r'cid=(\d+)', p.get('googleMapsUri', ''))
                cid = cid_m.group(1) if cid_m else None
                if not cid:
                    continue
                rating = p.get('rating', 0)
                count = p.get('userRatingCount', 0)
                if rating < MIN_RATING or count < MIN_REVIEWS:
                    continue
                address = p.get('formattedAddress', '')
                keywords = AREA_KEYWORDS.get(hub_label)
                if keywords and not any(k in address for k in keywords):
                    print(f"  DROPPED (address doesn't match {hub_label}): "
                          f"{p.get('displayName', {}).get('text', '')} | {address}", flush=True)
                    continue
                key = f"{cat_label}::{cid}"
                if key in all_results:
                    continue
                all_results[key] = {
                    'place_id': p.get('id'),
                    'name': p.get('displayName', {}).get('text', ''),
                    'address': address,
                    'rating': rating,
                    'userRatingCount': count,
                    'priceLevel': p.get('priceLevel'),
                    'googleMapsUri': p.get('googleMapsUri'),
                    'location': p.get('location'),
                    'types': p.get('types'),
                    'cid': cid,
                    'cat_label': cat_label,
                    'area_label': hub_label,
                }
            time.sleep(0.15)

print("total unique (cat,cid) candidates:", len(all_results))
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
json.dump(all_results, open(OUT_PATH, 'w'), ensure_ascii=False, indent=1)

for cat_label in CATEGORY_QUERIES:
    print(f"--- {cat_label} ---")
    rows = [v for v in all_results.values() if v['cat_label'] == cat_label]
    for v in sorted(rows, key=lambda x: -x['rating']):
        print(f"{v['rating']:.1f} ({v['userRatingCount']:>5}) [{v['area_label']}] {v['name']} | {v['address']}")
