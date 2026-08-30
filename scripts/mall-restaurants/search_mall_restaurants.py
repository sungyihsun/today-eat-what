# -*- coding: utf-8 -*-
"""
One-off: find restaurants that are literally inside 5 named indoor shopping
malls (新竹巨城/新竹大遠百/竹北遠百/享平方/iFG遠雄自由行), for a new
"雨天首選" (rainy-day pick) category — the point is you can reach these
without getting wet, so "near the mall" or "across the street from it" does
NOT qualify, only tenants actually inside the building.

Two phases:
1. Resolve each mall's own canonical place (Text Search by name, no location
   bias) to get its real formattedAddress/location. A tenant's own address
   almost always repeats the mall's street address (same building, different
   floor/unit), so this address is reused as a same-building filter in phase 2
   instead of guessing street numbers by hand.
2. For each mall, search nearby (tight radius so results don't spill into
   neighboring standalone restaurants across the street) with a handful of
   query variants for dish-type variety, then keep only candidates whose own
   formattedAddress shares the mall's street-address prefix.

Usage (CI): GOOGLE_PLACES_API_KEY=... python3 scripts/mall-restaurants/search_mall_restaurants.py
"""
import json, os, re, urllib.request, urllib.error, time

OUT_PATH = os.environ.get("MALL_CANDIDATES_PATH", "candidate-results/mall-candidates.json")
MALLS_OUT_PATH = os.environ.get("MALL_ANCHORS_PATH", "candidate-results/mall-anchors.json")

MIN_RATING = 4.0
MIN_REVIEWS = 20

KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
if not KEY:
    raise SystemExit("Missing GOOGLE_PLACES_API_KEY")

# The 5 malls, in the exact colloquial names people search for them.
MALL_NAMES = {
    "新竹巨城": "遠東巨城購物中心",
    "新竹大遠百": "新竹大遠百",
    "竹北遠百": "遠東百貨 竹北店",
    "享平方": "享平方 竹北",
    "iFG遠雄自由行": "iFG遠雄自由行 竹北",
}

# Generic dish-type query variants tried at every mall, for cuisine variety
# instead of just whatever ranks first for a bare "餐廳" search.
QUERY_SUFFIXES = [
    "餐廳", "美食", "咖啡廳", "甜點", "火鍋", "日式料理", "義式料理", "牛排",
    "燒烤", "港式", "小吃", "飲料店", "素食", "早午餐", "拉麵", "壽司", "韓式料理",
]


def search_text(query, lat=None, lng=None, radius=None):
    body = {"textQuery": query, "languageCode": "zh-TW"}
    if lat is not None:
        body["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius}}
    url = "https://places.googleapis.com/v1/places:searchText"
    field_mask = ("places.id,places.displayName,places.formattedAddress,places.rating,"
                  "places.userRatingCount,places.priceLevel,places.googleMapsUri,"
                  "places.location,places.types")
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST', headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": KEY, "X-Goog-FieldMask": field_mask,
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode('utf-8')}


def street_prefix(address):
    """Everything up to and including the building number, e.g.
    '300台灣新竹市東區中央路241號' -> '新竹市東區中央路241號' (drop the leading
    postal code digits which aren't part of the actual street text)."""
    m = re.search(r'(?:台灣)?(.+?\d+號)', address)
    return m.group(1) if m else address


# Phase 1: resolve each mall's own canonical address/location.
anchors = {}
for label, query in MALL_NAMES.items():
    data = search_text(query)
    places = data.get('places', [])
    if not places:
        print(f"COULD NOT RESOLVE MALL: {label} ({query}) -> {data}")
        continue
    p = places[0]
    addr = p.get('formattedAddress', '')
    loc = p.get('location', {})
    anchors[label] = {
        'resolved_name': p.get('displayName', {}).get('text', ''),
        'address': addr,
        'street_prefix': street_prefix(addr),
        'lat': loc.get('latitude'),
        'lng': loc.get('longitude'),
    }
    print(f"resolved {label} -> {anchors[label]}")
    time.sleep(0.15)

os.makedirs(os.path.dirname(MALLS_OUT_PATH), exist_ok=True)
json.dump(anchors, open(MALLS_OUT_PATH, 'w'), ensure_ascii=False, indent=1)

# Phase 2: search each mall's neighborhood, keep only same-building results.
# Round 1 prefixed every query with the mall's own name (e.g. "iFG遠雄自由行
# 餐廳") and got ZERO results for iFG遠雄自由行/享平方 — Text Search treats
# textQuery as a real text-match, not just a location hint, so a colloquial
# mall name that doesn't literally appear in nearby listings' names/descriptions
# suppressed results outright even with locationBias set. Fixed: drop the mall
# name from the query text entirely and let locationBias + the tight radius +
# the street_prefix address check (below) do 100% of the disambiguation —
# exactly how the existing Taiwan-area food search already works.
all_results = {}
for label, anchor in anchors.items():
    lat, lng = anchor['lat'], anchor['lng']
    if lat is None:
        continue
    prefix = anchor['street_prefix']
    for suffix in QUERY_SUFFIXES:
        query = suffix
        data = search_text(query, lat, lng, radius=300.0)
        places = data.get('places', [])
        print(f"{label} / {suffix}: {len(places)} results", flush=True)
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
            if prefix not in address:
                continue
            key = f"{label}::{cid}"
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
                'mall_label': label,
            }
        time.sleep(0.15)

print("total unique (mall,cid) candidates:", len(all_results))
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
json.dump(all_results, open(OUT_PATH, 'w'), ensure_ascii=False, indent=1)

for label in anchors:
    print(f"--- {label} ---")
    rows = [v for v in all_results.values() if v['mall_label'] == label]
    for v in sorted(rows, key=lambda x: -x['rating']):
        print(f"{v['rating']:.1f} ({v['userRatingCount']:>5}) {v['name']} | {v['address']}")
