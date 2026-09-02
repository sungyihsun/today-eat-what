# -*- coding: utf-8 -*-
"""
One-off: resolve a handful of specific, user-named Busan places (not a
category search) via Google Places Text Search, one query per place. Used
when the user already knows exactly which restaurant/attraction they want
added, rather than asking for "N more X near Y".

Usage (CI): GOOGLE_PLACES_API_KEY=... python3 scripts/busan-trip/search_busan_named_places.py
"""
import json, os, re, time, urllib.request, urllib.error

OUT_PATH = os.environ.get("BUSAN_NAMED_CANDIDATES_PATH", "candidate-results/busan-named-places-candidates.json")

KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
if not KEY:
    raise SystemExit("Missing GOOGLE_PLACES_API_KEY")

FIELD_MASK = ("places.id,places.displayName,places.formattedAddress,places.rating,"
              "places.userRatingCount,places.priceLevel,places.googleMapsUri,"
              "places.location,places.types,places.primaryType")

# label -> query string to resolve via Text Search.
QUERIES = {
    "31cm 刀削麵": "31cm 칼국수 해운대",
    "ARTE MUSEUM": "아르떼뮤지엄 부산",
    "白淺灘文化村": "흰여울문화마을",
}


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


results = {}
for label, query in QUERIES.items():
    data = search_text(query)
    places = data.get('places', [])
    if not places:
        print(f"COULD NOT RESOLVE: {label} ({query}) -> {data}")
        continue
    # print top 3 so a same-name mismatch (wrong branch/city) can be caught by eye
    for i, p in enumerate(places[:3]):
        cid_m = re.search(r'cid=(\d+)', p.get('googleMapsUri', ''))
        cid = cid_m.group(1) if cid_m else None
        entry = {
            'place_id': p.get('id'),
            'name': p.get('displayName', {}).get('text', ''),
            'address': p.get('formattedAddress', ''),
            'rating': p.get('rating', 0),
            'userRatingCount': p.get('userRatingCount', 0),
            'priceLevel': p.get('priceLevel'),
            'googleMapsUri': p.get('googleMapsUri'),
            'location': p.get('location'),
            'types': p.get('types'),
            'primaryType': p.get('primaryType'),
            'cid': cid,
            'query_label': label,
            'rank': i,
        }
        results[f"{label}::{i}"] = entry
        print(f"{label} [{i}] {entry['rating']} ({entry['userRatingCount']}) {entry['name']} | {entry['address']} | {entry['types'][:4] if entry['types'] else None}")
    time.sleep(0.15)

os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
json.dump(results, open(OUT_PATH, 'w'), ensure_ascii=False, indent=1)
print("done, total entries:", len(results))
