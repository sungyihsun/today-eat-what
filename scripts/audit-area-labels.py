# -*- coding: utf-8 -*-
"""
One-off / re-runnable audit: for every restaurant embedded in index.html,
re-look-up its place on Google Places by name (biased to its stored lat/lng),
confirm the result is the SAME place (by matching the cid encoded in its
mapsUrl), then check whether the place's real formattedAddress is consistent
with the `area` field we've tagged it with on the site.

This is the check that was missing when 艾薇越式河粉 got tagged area:"竹北"
despite its real address being in 新竹市 — the original batch-add trusted
the search's locationBias area label instead of the place's own address.

Run via GitHub Actions (push to DEV touching this file), since the sandbox
that edits this repo can't reach places.googleapis.com without the secret
key. Prints one line per restaurant; anything not "OK" needs a manual look.

Usage (CI): GOOGLE_PLACES_API_KEY=... python3 scripts/audit-area-labels.py
"""
import json, os, re, sys, time, urllib.request, urllib.error

KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
if not KEY:
    raise SystemExit("Missing GOOGLE_PLACES_API_KEY")

INDEX_HTML_PATH = "index.html"

# area value on the site -> substring(s) that MUST appear in the real
# formattedAddress for that tag to be considered correct. Keep in sync with
# the AREA_KEYWORDS in the add-restaurant skill scripts.
AREA_KEYWORDS = {
    "新竹市": ["新竹市"],
    "竹北": ["竹北市"],
    "桃園": ["桃園市"],
}


def search_text(query, lat, lng, radius=600.0):
    url = "https://places.googleapis.com/v1/places:searchText"
    body = json.dumps({
        "textQuery": query, "languageCode": "zh-TW",
        "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius}}
    }).encode('utf-8')
    field_mask = "places.formattedAddress,places.googleMapsUri,places.displayName"
    req = urllib.request.Request(url, data=body, method='POST', headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": KEY, "X-Goog-FieldMask": field_mask,
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode('utf-8')}


html = open(INDEX_HTML_PATH, encoding='utf-8').read()
entry_re = re.compile(
    r'\{name:"((?:[^"\\]|\\.)*)",\s*area:"((?:[^"\\]|\\.)*)".*?lat:([\d.\-]+),\s*lng:([\d.\-]+).*?mapsUrl:"((?:[^"\\]|\\.)*)"\}',
)
restaurants = []
for m in entry_re.finditer(html):
    name, area, lat, lng, maps_url = m.groups()
    cid_m = re.search(r'cid=(\d+)', maps_url)
    if not cid_m:
        continue
    restaurants.append({
        'name': name, 'area': area, 'lat': float(lat), 'lng': float(lng), 'cid': cid_m.group(1),
    })

print(f"parsed {len(restaurants)} restaurants with a cid", flush=True)

mismatches = []
unverified = []
for i, r in enumerate(restaurants):
    keywords = AREA_KEYWORDS.get(r['area'])
    if not keywords:
        print(f"[{i+1}/{len(restaurants)}] SKIP (no keyword rule for area={r['area']!r}) {r['name']}", flush=True)
        continue
    data = search_text(r['name'], r['lat'], r['lng'])
    places = data.get('places', [])
    matched = None
    for p in places:
        cid_m = re.search(r'cid=(\d+)', p.get('googleMapsUri', ''))
        if cid_m and cid_m.group(1) == r['cid']:
            matched = p
            break
    if not matched:
        print(f"[{i+1}/{len(restaurants)}] UNVERIFIED (cid not found in re-search results) {r['name']}", flush=True)
        unverified.append(r['name'])
        time.sleep(0.15)
        continue
    addr = matched.get('formattedAddress', '')
    ok = any(k in addr for k in keywords)
    status = "OK" if ok else "MISMATCH"
    print(f"[{i+1}/{len(restaurants)}] {status} area={r['area']!r} addr={addr!r} {r['name']}", flush=True)
    if not ok:
        mismatches.append({'name': r['name'], 'area': r['area'], 'address': addr})
    time.sleep(0.15)

print()
print("=== SUMMARY ===")
print(f"total checked: {len(restaurants)}")
print(f"mismatches: {len(mismatches)}")
for m in mismatches:
    print(" -", m)
print(f"unverified (couldn't re-match by cid): {len(unverified)}")
for n in unverified:
    print(" -", n)

if mismatches:
    sys.exit(1)
