# -*- coding: utf-8 -*-
"""
One-off: find 餐廳 (restaurants) and 逛街 (shopping) spots in 靑沙浦
(Cheongsapo), Busan — a small fishing-village area near Haeundae, known for
its lighthouse/harbor and the Dalmaji-gil cafe street above it. Same
places:searchNearby + haversine-distance technique as
scripts/busan-trip/search_seomyeon_shopping.py.

Usage (CI): GOOGLE_PLACES_API_KEY=... python3 scripts/busan-trip/search_cheongsapo.py
"""
import json, os, re, time, urllib.request, urllib.error

OUT_PATH = os.environ.get("CHEONGSAPO_CANDIDATES_PATH", "candidate-results/cheongsapo-candidates.json")
ANCHOR_OUT_PATH = os.environ.get("CHEONGSAPO_ANCHOR_PATH", "candidate-results/cheongsapo-anchor.json")

STATION_QUERY = "청사포"
RADIUS_M = 900.0
MIN_RATING = 4.0
MIN_REVIEWS = 15

KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
if not KEY:
    raise SystemExit("Missing GOOGLE_PLACES_API_KEY")

FIELD_MASK = ("places.id,places.displayName,places.formattedAddress,places.rating,"
              "places.userRatingCount,places.priceLevel,places.googleMapsUri,"
              "places.location,places.types,places.primaryType")


def search_text(query):
    url = "https://places.googleapis.com/v1/places:searchText"
    body = {"textQuery": query, "languageCode": "zh-TW"}
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST', headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": KEY, "X-Goog-FieldMask": FIELD_MASK,
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode('utf-8')}


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


def haversine_m(lat1, lng1, lat2, lng2):
    from math import radians, sin, cos, asin, sqrt
    R = 6371000.0
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlmb = radians(lng2 - lng1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlmb / 2) ** 2
    return 2 * R * asin(sqrt(a))


# Phase 1: resolve 청사포 itself.
data = search_text(STATION_QUERY)
places = data.get('places', [])
if not places:
    raise SystemExit(f"COULD NOT RESOLVE: {STATION_QUERY} -> {data}")
place = places[0]
ploc = place.get('location', {})
anchor = {
    'resolved_name': place.get('displayName', {}).get('text', ''),
    'address': place.get('formattedAddress', ''),
    'lat': ploc.get('latitude'),
    'lng': ploc.get('longitude'),
}
print("resolved 靑沙浦 ->", anchor)
os.makedirs(os.path.dirname(ANCHOR_OUT_PATH), exist_ok=True)
json.dump(anchor, open(ANCHOR_OUT_PATH, 'w'), ensure_ascii=False, indent=1)

# Phase 2: 餐廳/逛街 candidate types nearby.
CATEGORY_TYPE_BATCHES = {
    "餐廳": [
        ["restaurant"],
        ["seafood_restaurant", "korean_restaurant"],
        ["cafe", "coffee_shop"],
    ],
    "逛街": [
        ["shopping_mall", "gift_shop"],
        ["market", "department_store"],
    ],
}

all_results = {}
lat, lng = anchor['lat'], anchor['lng']
for cat_label, batches in CATEGORY_TYPE_BATCHES.items():
    for included_types in batches:
        data = search_nearby(lat, lng, RADIUS_M, included_types)
        places = data.get('places', [])
        print(f"{cat_label} / {included_types}: {len(places)} results", flush=True)
        for p in places:
            cid_m = re.search(r'cid=(\d+)', p.get('googleMapsUri', ''))
            cid = cid_m.group(1) if cid_m else None
            if not cid:
                continue
            key = f"{cat_label}::{cid}"
            if key in all_results:
                continue
            rating = p.get('rating', 0)
            count = p.get('userRatingCount', 0)
            if rating < MIN_RATING or count < MIN_REVIEWS:
                continue
            loc = p.get('location') or {}
            dist = round(haversine_m(lat, lng, loc['latitude'], loc['longitude']), 1) if loc.get('latitude') is not None else None
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
                'distance_m': dist,
            }
        time.sleep(0.15)

print("total unique candidates:", len(all_results))
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
json.dump(all_results, open(OUT_PATH, 'w'), ensure_ascii=False, indent=1)

for cat_label in CATEGORY_TYPE_BATCHES:
    print(f"--- {cat_label} ---")
    rows = [v for v in all_results.values() if v['cat_label'] == cat_label]
    for v in sorted(rows, key=lambda x: (x['distance_m'] is None, x['distance_m'])):
        print(f"{v['distance_m']:>6}m {v['rating']:.1f} ({v['userRatingCount']:>4}) {v['name']} | {v['address']} | {v['types'][:4]}")
