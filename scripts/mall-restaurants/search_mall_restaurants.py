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

# searchNearby's includedTypes, tried a few at a time (Google caps how many
# types one call accepts usefully) for cuisine variety instead of just
# whatever "restaurant" alone ranks first.
INCLUDED_TYPE_BATCHES = [
    ["restaurant"],
    ["cafe", "coffee_shop", "bakery", "dessert_shop"],
    ["japanese_restaurant", "italian_restaurant", "korean_restaurant", "thai_restaurant"],
    ["steak_house", "hot_pot_restaurant", "seafood_restaurant", "barbecue_restaurant"],
    ["chinese_restaurant", "buffet_restaurant", "sushi_restaurant", "ramen_restaurant"],
]


FIELD_MASK = ("places.id,places.displayName,places.formattedAddress,places.rating,"
              "places.userRatingCount,places.priceLevel,places.googleMapsUri,"
              "places.location,places.types")


def search_text(query, lat=None, lng=None, radius=None):
    body = {"textQuery": query, "languageCode": "zh-TW"}
    if lat is not None:
        body["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius}}
    url = "https://places.googleapis.com/v1/places:searchText"
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST', headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": KEY, "X-Goog-FieldMask": FIELD_MASK,
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode('utf-8')}


def search_nearby(lat, lng, radius, included_types):
    """places:searchNearby — unlike searchText+locationBias (a soft text-
    relevance bias that returned ZERO hits for several malls in earlier
    rounds because a plain one-word query has no proximity guarantee at
    all), this endpoint does a real radius-restricted lookup: every result
    is guaranteed to be inside the circle, no free-text matching involved."""
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


def street_prefix(address):
    """Everything up to and including the building number, e.g.
    '300台灣新竹市東區中央路241號' -> '新竹市東區中央路241號' (drop the leading
    postal code digits which aren't part of the actual street text)."""
    m = re.search(r'(?:台灣)?(.+?\d+號)', address)
    return m.group(1) if m else address


def haversine_m(lat1, lng1, lat2, lng2):
    from math import radians, sin, cos, asin, sqrt
    R = 6371000.0
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlmb = radians(lng2 - lng1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlmb / 2) ** 2
    return 2 * R * asin(sqrt(a))


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

# Phase 2: search each mall's neighborhood.
# Round 1 (searchText+locationBias with the mall name in the query text) and
# round 2 (searchText+locationBias, mall name dropped) both returned ZERO for
# most malls — a plain query has no real proximity guarantee with that
# endpoint. Round 3 switched to places:searchNearby (a true radius
# restriction) plus a strict "candidate's own formattedAddress must contain
# the mall's exact street-address substring" filter — that still starved
# 新竹巨城/iFG遠雄自由行/享平方 down to 0-1, because real tenants often don't
# repeat the mall's official registered address verbatim (different unit
# suffix, a side-entrance road name, etc.) even though they're genuinely
# inside the building. Fixed here: keep searchNearby's real radius
# restriction, but replace the fragile string-prefix gate with an actual
# haversine distance in meters from the mall's anchor point — every
# candidate's distance is recorded so the review step can pick a sane cutoff
# (a mall building is usually well under 120m across; a plain radius filter
# at search time can't be tighter than the search itself allows for recall).
all_results = {}
for label, anchor in anchors.items():
    lat, lng = anchor['lat'], anchor['lng']
    if lat is None:
        continue
    for included_types in INCLUDED_TYPE_BATCHES:
        data = search_nearby(lat, lng, 300.0, included_types)
        places = data.get('places', [])
        print(f"{label} / {included_types}: {len(places)} results", flush=True)
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
            ploc = p.get('location') or {}
            dist = None
            if ploc.get('latitude') is not None:
                dist = round(haversine_m(lat, lng, ploc['latitude'], ploc['longitude']), 1)
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
                'distance_m': dist,
                'address_matches_mall': anchor['street_prefix'] in address,
            }
        time.sleep(0.15)

print("total unique (mall,cid) candidates:", len(all_results))
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
json.dump(all_results, open(OUT_PATH, 'w'), ensure_ascii=False, indent=1)

for label in anchors:
    print(f"--- {label} ---")
    rows = [v for v in all_results.values() if v['mall_label'] == label]
    for v in sorted(rows, key=lambda x: (x['distance_m'] is None, x['distance_m'])):
        print(f"{v['distance_m']:>6}m  {v['rating']:.1f} ({v['userRatingCount']:>5}) "
              f"match={v['address_matches_mall']} {v['name']} | {v['address']}")
