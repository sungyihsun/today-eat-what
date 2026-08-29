# -*- coding: utf-8 -*-
"""
One-off: search Google Places (New) Text Search for restaurant candidates near
each stop of the user's 釜山 5天4夜 itinerary (2026/9/3-9/7). Not part of the
add-restaurant skill's reusable Taiwan pipeline — this is trip-specific data
for a new, independent "旅遊版" page, so no AREA_KEYWORDS address safeguard
here (that check is about which of 3 fixed Taiwan `area` values to assign;
there's no such assignment happening for trip data). Instead this just prints
formattedAddress for every candidate so results can be eyeballed against the
intended neighborhood before picking a final list.

Usage (CI): GOOGLE_PLACES_API_KEY=... python3 scripts/busan-trip/search_busan_restaurants.py
"""
import json, os, urllib.request, urllib.error, time, re

OUT_PATH = os.environ.get("BUSAN_CANDIDATES_PATH", "candidate-results/busan-candidates.json")

MIN_RATING = 4.0
MIN_REVIEWS = 30

KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
if not KEY:
    raise SystemExit("Missing GOOGLE_PLACES_API_KEY")

# stop label -> (lat, lng) center for locationBias, matching the itinerary's
# route stops day by day.
AREAS = {
    "西面": (35.1580, 129.0597),
    "田浦": (35.1583, 129.0678),
    "甘川洞": (35.0972, 129.0106),
    "南浦洞": (35.0980, 129.0306),
    "海雲台": (35.1587, 129.1604),
    "청사포_靑沙浦": (35.1656, 129.1774),
    "廣安里": (35.1532, 129.1187),
    "民樂會": (35.1543, 129.1257),
}

# stop label -> list of query strings to try for that stop.
QUERIES = {
    "西面": ["西面 맛집", "서면 고기집", "서면 국밥"],
    "田浦": ["전포 카페", "전포동 맛집"],
    "甘川洞": ["감천문화마을 맛집"],
    "南浦洞": ["남포동 맛집", "국제시장 맛집"],
    "海雲台": ["해운대 맛집"],
    "청사포_靑沙浦": ["청사포 맛집", "청사포 카페"],
    "廣安里": ["광안리 맛집"],
    "民樂會": ["민락회센터 맛집", "민락동 회센터"],
}


def search_text(query, lat, lng, radius=1200.0):
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
        print(f"{area_label} / {q}: {len(places)} results", flush=True)
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
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
json.dump(all_results, open(OUT_PATH, 'w'), ensure_ascii=False, indent=1)

for area_label in QUERIES:
    print(f"--- {area_label} ---")
    for cid, v in sorted(all_results.items(), key=lambda x: -x[1]['rating']):
        if v['area_label'] == area_label:
            print(f"{v['rating']:.1f} ({v['userRatingCount']:>5}) {v['name']} | {v['address']} | types={v['types']}")
