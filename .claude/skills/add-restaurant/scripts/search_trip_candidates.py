# -*- coding: utf-8 -*-
"""
Trip-mode candidate search (separate from search_candidates.py, which the Taichung sweep
edits in place). Input JSON (env TRIP_SEARCH_IN):
  {"centers": {"博多": [lat,lng], ...}, "radius": 4000, "address_must_contain": ["福岡市"],
   "min_rating": 4.0, "min_reviews": 30, "exclude_details": ["candidate-results/fukuoka-details.json", ...],
   "queries": ["福岡 刺身 居酒屋", ...]}
Output (env TRIP_SEARCH_OUT): {place_id: {name, address, rating, userRatingCount, types, location, googleMapsUri, queries:[...]}}
Already-used places (place ids found in `exclude_details`) are dropped. Language is Japanese.
"""
import json, os, sys, time, urllib.request, urllib.error

KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
if not KEY:
    sys.exit("Missing GOOGLE_PLACES_API_KEY")
cfg = json.load(open(os.environ["TRIP_SEARCH_IN"], encoding="utf-8"))
OUT = os.environ["TRIP_SEARCH_OUT"]

used = set()
for p in cfg.get("exclude_details", []):
    try:
        used |= {v.get("id") for v in json.load(open(p, encoding="utf-8")).values()}
    except FileNotFoundError:
        pass


def search(q, lat, lng, radius):
    body = json.dumps({"textQuery": q, "languageCode": "ja",
                       "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": float(radius)}}}).encode()
    req = urllib.request.Request("https://places.googleapis.com/v1/places:searchText", data=body, method="POST", headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": KEY,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.rating,places.userRatingCount,places.googleMapsUri,places.location,places.types"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode()).get("places", [])
    except urllib.error.HTTPError as e:
        print("ERR", q, e.read().decode()[:200])
        return []


found = {}
for q in cfg["queries"]:
    n = 0
    for label, (lat, lng) in cfg["centers"].items():
        for p in search(q, lat, lng, cfg.get("radius", 4000)):
            pid = p.get("id")
            if pid in used:
                continue
            addr = p.get("formattedAddress", "")
            if not any(k in addr for k in cfg["address_must_contain"]):
                continue
            if p.get("rating", 0) < cfg.get("min_rating", 4.0) or p.get("userRatingCount", 0) < cfg.get("min_reviews", 30):
                continue
            rec = found.setdefault(pid, {"name": p["displayName"]["text"], "address": addr, "rating": p.get("rating"),
                                         "userRatingCount": p.get("userRatingCount"), "types": p.get("types"),
                                         "location": p.get("location"), "googleMapsUri": p.get("googleMapsUri"), "queries": []})
            if q not in rec["queries"]:
                rec["queries"].append(q)
                n += 1
        time.sleep(0.12)
    print(f"{q}: +{n}", flush=True)

json.dump(found, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("total", len(found))
