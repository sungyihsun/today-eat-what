# -*- coding: utf-8 -*-
"""
Resolve a hand-written list of NAMED places (attractions) to Place Details in one go.
Used for trip-mode attractions that are worth a visit but are not found by the
restaurant-style area search (day trips such as 太宰府 / 糸島 live outside the city).

Input  (env NAMED_PLACES_IN):  [{"key": "...", "query": "太宰府天満宮", "lat":.., "lng":.., "expect": ["太宰府市"]}, ...]
Output (env NAMED_PLACES_OUT): {raw Google name: details + _photo_urls + _hoursweek + _query_key}
Takes the first Text Search hit whose address contains one of `expect`; a query with
no such hit is reported and makes the script exit non-zero.
"""
import json, os, sys, time, urllib.request, urllib.error

KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
if not KEY:
    sys.exit("Missing GOOGLE_PLACES_API_KEY")
IN, OUT = os.environ["NAMED_PLACES_IN"], os.environ["NAMED_PLACES_OUT"]
LANG = "ja"


def call(url, body=None, mask=""):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 method="POST" if body else "GET",
                                 headers={"Content-Type": "application/json", "X-Goog-Api-Key": KEY,
                                          "X-Goog-FieldMask": mask})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


opener = urllib.request.build_opener(NoRedirect)


def photo_url(name):
    url = f"https://places.googleapis.com/v1/{name}/media?maxWidthPx=800&maxHeightPx=800&key={KEY}"
    try:
        opener.open(urllib.request.Request(url), timeout=20)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303):
            return e.headers.get("Location")
    return None


def hours(oh):
    week = [[] for _ in range(7)]
    for p in (oh or {}).get("periods", []):
        o, c = p.get("open"), p.get("close")
        if not o or not c:
            continue
        od, cd = (o["day"] + 6) % 7, (c["day"] + 6) % 7
        om, cm = o["hour"] * 60 + o["minute"], c["hour"] * 60 + c["minute"]
        week[od].append([om, (cm if cm > om else cm + 1440) if cd == od else cm + 1440])
    for d in week:
        d.sort()
    return week


results, bad = {}, []
for q in json.load(open(IN, encoding="utf-8")):
    if q.get("place_id"):
        pick = {"id": q["place_id"]}  # already chosen from a frozen search result
        print(f"[{q['key']}] place_id {q['place_id']}")
    else:
        data = call("https://places.googleapis.com/v1/places:searchText",
                    {"textQuery": q["query"], "languageCode": LANG,
                     "locationBias": {"circle": {"center": {"latitude": q["lat"], "longitude": q["lng"]}, "radius": 20000.0}}},
                    "places.id,places.displayName,places.formattedAddress,places.rating,places.userRatingCount")
        hits = data.get("places", [])
        print(f"[{q['key']}] {q['query']}:")
        for h in hits[:4]:
            print("   ", h.get("displayName", {}).get("text"), "|", h.get("formattedAddress"), "|", h.get("rating"), h.get("userRatingCount"))
        pick = next((h for h in hits if any(k in h.get("formattedAddress", "") for k in q["expect"])), None)
        if not pick:
            bad.append(q["key"])
            continue
    d = call(f"https://places.googleapis.com/v1/places/{pick['id']}?languageCode={LANG}", None,
             "id,displayName,formattedAddress,rating,userRatingCount,priceLevel,nationalPhoneNumber,"
             "regularOpeningHours,parkingOptions,photos,primaryType,types,googleMapsUri,location")
    if not any(k in d.get("formattedAddress", "") for k in q["expect"]):
        bad.append(q["key"])
        print("   ADDRESS MISMATCH", d.get("formattedAddress"))
        continue
    d["_photo_urls"] = [u for u in (photo_url(p["name"]) for p in d.get("photos", [])[:3]) if u]
    d["_hoursweek"] = hours(d.get("regularOpeningHours"))
    d["_query_key"] = q["key"]
    results[d["displayName"]["text"]] = d
    print("   -> PICKED", d["displayName"]["text"], "photos:", len(d["_photo_urls"]), flush=True)
    time.sleep(0.2)

json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
if bad:
    sys.exit(f"unresolved: {bad}")
