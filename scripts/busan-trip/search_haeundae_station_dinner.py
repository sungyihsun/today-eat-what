# -*- coding: utf-8 -*-
"""
One-off: find dinner restaurants on the street in front of Haeundae Station
(해운대역), Busan — user is there right now wanting dinner options tonight.
Same anchor-resolve + places:searchNearby technique as
scripts/busan-trip/search_busan_hotel_breakfast.py.

Usage (CI): GOOGLE_PLACES_API_KEY=... python3 scripts/busan-trip/search_haeundae_station_dinner.py
"""
import json, os, re, time, urllib.request, urllib.error

OUT_PATH = os.environ.get("HAEUNDAE_STATION_CANDIDATES_PATH", "candidate-results/haeundae-station-dinner-candidates.json")
ANCHOR_OUT_PATH = os.environ.get("HAEUNDAE_STATION_ANCHOR_PATH", "candidate-results/haeundae-station-anchor.json")

STATION_QUERY = "해운대역"
RADIUS_M = 600.0
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


# Phase 1: resolve the station.
data = search_text(STATION_QUERY)
places = data.get('places', [])
if not places:
    raise SystemExit(f"COULD NOT RESOLVE STATION: {STATION_QUERY} -> {data}")
station = places[0]
sloc = station.get('location', {})
anchor = {
    'resolved_name': station.get('displayName', {}).get('text', ''),
    'address': station.get('formattedAddress', ''),
    'lat': sloc.get('latitude'),
    'lng': sloc.get('longitude'),
}
print("resolved station ->", anchor)
os.makedirs(os.path.dirname(ANCHOR_OUT_PATH), exist_ok=True)
json.dump(anchor, open(ANCHOR_OUT_PATH, 'w'), ensure_ascii=False, indent=1)

# Phase 2: dinner-appropriate place types nearby.
TYPE_BATCHES = [
    ["korean_restaurant"],
    ["korean_barbecue_restaurant", "barbecue_restaurant"],
    ["seafood_restaurant", "japanese_restaurant"],
    ["hot_pot_restaurant", "chinese_restaurant"],
    ["restaurant"],
]

all_results = {}
lat, lng = anchor['lat'], anchor['lng']
for included_types in TYPE_BATCHES:
    data = search_nearby(lat, lng, RADIUS_M, included_types)
    places = data.get('places', [])
    print(f"{included_types}: {len(places)} results", flush=True)
    for p in places:
        cid_m = re.search(r'cid=(\d+)', p.get('googleMapsUri', ''))
        cid = cid_m.group(1) if cid_m else None
        if not cid or cid in all_results:
            continue
        rating = p.get('rating', 0)
        count = p.get('userRatingCount', 0)
        if rating < MIN_RATING or count < MIN_REVIEWS:
            continue
        ploc = p.get('location') or {}
        dist = round(haversine_m(lat, lng, ploc['latitude'], ploc['longitude']), 1) if ploc.get('latitude') is not None else None
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
            'cid': cid,
            'distance_m': dist,
        }
    time.sleep(0.15)

print("total unique candidates:", len(all_results))
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
json.dump(all_results, open(OUT_PATH, 'w'), ensure_ascii=False, indent=1)

for v in sorted(all_results.values(), key=lambda x: (x['distance_m'] is None, x['distance_m'])):
    print(f"{v['distance_m']:>6}m  {v['rating']:.1f} ({v['userRatingCount']:>4}) {v['name']} | {v['address']} | {v['types'][:4]}")
