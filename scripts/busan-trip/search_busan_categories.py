# -*- coding: utf-8 -*-
"""
One-off: expand busanRestaurants coverage for five requested dish
categories (韓式燒烤/石鍋拌飯/人蔘雞湯/辣炒年糕/海鮮) to 10+ each. Unlike
search_busan_restaurants.py (which searched near specific itinerary stops),
this searches city-wide — several queries per category, each run from
multiple Busan hub points — since the goal now is category coverage across
the city, not stops along one 5-day route.

Usage (CI): GOOGLE_PLACES_API_KEY=... python3 scripts/busan-trip/search_busan_categories.py
"""
import json, os, urllib.request, urllib.error, time, re

OUT_PATH = os.environ.get("BUSAN_CAT_CANDIDATES_PATH", "candidate-results/busan-cat-candidates.json")

MIN_RATING = 4.0
MIN_REVIEWS = 30

KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
if not KEY:
    raise SystemExit("Missing GOOGLE_PLACES_API_KEY")

# Hub points spread across central Busan, used as locationBias centers for
# every category query so results aren't clustered around just one district.
HUBS = {
    "西面": (35.1580, 129.0597),
    "南浦洞": (35.0980, 129.0306),
    "海雲台": (35.1587, 129.1604),
    "廣安里": (35.1532, 129.1187),
    "東萊": (35.2048, 129.0857),
}

# detail-cat label -> query strings to try at every hub above.
CATEGORY_QUERIES = {
    "燒烤": ["부산 고기집", "부산 소고기 맛집"],
    "石鍋拌飯": ["부산 돌솥비빔밥 맛집"],
    "人蔘雞湯": ["부산 삼계탕 맛집"],
    "辣炒年糕": ["부산 떡볶이 맛집"],
    "海鮮": ["부산 회 맛집", "부산 해산물 맛집"],
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
            data = search_text(q, lat, lng)
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
                key = f"{cat_label}::{cid}"
                if key in all_results:
                    continue
                all_results[key] = {
                    'place_id': p.get('id'),
                    'name': p.get('displayName', {}).get('text', ''),
                    'address': p.get('formattedAddress', ''),
                    'rating': rating,
                    'userRatingCount': count,
                    'priceLevel': p.get('priceLevel'),
                    'googleMapsUri': p.get('googleMapsUri'),
                    'location': p.get('location'),
                    'types': p.get('types'),
                    'cid': cid,
                    'cat_label': cat_label,
                    'near_hub': hub_label,
                }
            time.sleep(0.15)

print("total unique (cat,cid) candidates:", len(all_results))
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
json.dump(all_results, open(OUT_PATH, 'w'), ensure_ascii=False, indent=1)

for cat_label in CATEGORY_QUERIES:
    print(f"--- {cat_label} ---")
    rows = [v for v in all_results.values() if v['cat_label'] == cat_label]
    for v in sorted(rows, key=lambda x: -x['rating']):
        print(f"{v['rating']:.1f} ({v['userRatingCount']:>5}) {v['name']} | {v['address']}")
