# -*- coding: utf-8 -*-
"""
One-off: find 逛街 (shopping)/景點 (attractions)/母嬰用品 (baby & maternity
goods) spots in 西面 (Seomyeon), Busan, for 旅遊版 trip mode. Same
places:searchNearby + haversine-distance technique as
scripts/mall-restaurants/search_mall_restaurants.py — a real radius
restriction instead of the unreliable searchText+locationBias soft bias.

Usage (CI): GOOGLE_PLACES_API_KEY=... python3 scripts/busan-trip/search_seomyeon_shopping.py
"""
import json, os, re, time, urllib.request, urllib.error

OUT_PATH = os.environ.get("SEOMYEON_CANDIDATES_PATH", "candidate-results/seomyeon-shopping-candidates.json")

# 西面 hub, same center used throughout scripts/busan-trip/search_busan_categories.py.
CENTER = (35.1580, 129.0597)
RADIUS_M = 1500.0
MIN_RATING = 4.0
MIN_REVIEWS = 20

KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
if not KEY:
    raise SystemExit("Missing GOOGLE_PLACES_API_KEY")

FIELD_MASK = ("places.id,places.displayName,places.formattedAddress,places.rating,"
              "places.userRatingCount,places.priceLevel,places.googleMapsUri,"
              "places.location,places.types,places.primaryType")

# cat_label -> includedTypes tried (Google caps how many types are useful
# per call, so a few batches per category for variety).
CATEGORY_TYPE_BATCHES = {
    "逛街": [
        ["shopping_mall", "department_store"],
        ["market", "gift_shop"],
    ],
    "景點": [
        ["tourist_attraction", "historical_landmark"],
        ["art_gallery", "museum"],
        ["park", "plaza"],
    ],
    "母嬰用品": [
        ["baby_store"],
    ],
}


def search_nearby(lat, lng, radius, included_types):
    url = "https://places.googleapis.com/v1/places:searchNearby"
    body = {
        "includedTypes": included_types,
        "maxResultCount": 20,
        "languageCode": "zh-TW",
        "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius}},
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST', headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": KEY, "X-Goog-FieldMask": FIELD_MASK,
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode('utf-8')}


def search_text(query, lat, lng, radius):
    url = "https://places.googleapis.com/v1/places:searchText"
    body = {
        "textQuery": query, "languageCode": "zh-TW",
        "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius}},
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST', headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": KEY, "X-Goog-FieldMask": FIELD_MASK,
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode('utf-8')}


def haversine_m(lat1, lng1, lat2, lng2):
    from math import radians, sin, cos, asin, sqrt
    R = 6371000.0
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlmb = radians(lng2 - lng1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlmb / 2) ** 2
    return 2 * R * asin(sqrt(a))


all_results = {}
lat, lng = CENTER


def add_place(cat_label, p):
    cid_m = re.search(r'cid=(\d+)', p.get('googleMapsUri', ''))
    cid = cid_m.group(1) if cid_m else None
    if not cid:
        return
    key = f"{cat_label}::{cid}"
    if key in all_results:
        return
    rating = p.get('rating', 0)
    count = p.get('userRatingCount', 0)
    if rating < MIN_RATING or count < MIN_REVIEWS:
        return
    ploc = p.get('location') or {}
    dist = round(haversine_m(lat, lng, ploc['latitude'], ploc['longitude']), 1) if ploc.get('latitude') is not None else None
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
        'primaryType': p.get('primaryType'),
        'cid': cid,
        'cat_label': cat_label,
    }


for cat_label, batches in CATEGORY_TYPE_BATCHES.items():
    for included_types in batches:
        data = search_nearby(lat, lng, RADIUS_M, included_types)
        places = data.get('places', [])
        print(f"{cat_label} / {included_types}: {len(places)} results", flush=True)
        for p in places:
            add_place(cat_label, p)
        time.sleep(0.15)

# baby_store is a real Google type but 西面's coverage under it alone may be
# thin — supplement with text search using the actual Korean term shoppers
# search for, still biased to the same 西面 center.
for q in ["서면 아기용품점", "서면 유아용품점", "서면 임산부용품"]:
    data = search_text(q, lat, lng, RADIUS_M)
    places = data.get('places', [])
    print(f"母嬰用品 / {q}: {len(places)} results", flush=True)
    for p in places:
        add_place("母嬰用品", p)
    time.sleep(0.15)

print("total unique candidates:", len(all_results))
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
json.dump(all_results, open(OUT_PATH, 'w'), ensure_ascii=False, indent=1)

for cat_label in CATEGORY_TYPE_BATCHES:
    print(f"--- {cat_label} ---")
    rows = [v for v in all_results.values() if v['cat_label'] == cat_label]
    for v in sorted(rows, key=lambda x: (x['distance_m'] is None, x['distance_m'] or 0)):
        print(f"{v.get('distance_m')}m {v['rating']:.1f} ({v['userRatingCount']:>4}) {v['name']} | {v['address']} | {v['types'][:4]}")
