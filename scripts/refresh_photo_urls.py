# -*- coding: utf-8 -*-
"""
One-off maintenance: Google's Place Photo media URLs
(https://lh3.googleusercontent.com/place-photos/...) are signed/ephemeral —
they expire after some weeks, unlike the place itself. This site's data was
built in many batches over a long period, so the earliest batches' photo
URLs are now likely dead while recent ones still work.

Checks photos from THREE sources (the site's actual data model — see
supabase/README.md and index.html's own comments):
  - supabase/restaurants-import.csv: the canonical source for every Taiwan
    (新竹/竹北/桃園) restaurant. This is what QAS/PRD actually serve, via
    Supabase — NOT embeddedRestaurants, which is only the DEV/offline
    fallback array.
  - index.html's `const busanRestaurants = [...]`: 旅遊版 (釜山) data,
    deliberately kept OUT of Supabase (pure front-end).
  - index.html's `const taiwanClothingRestaurants = [...]`: 服飾 data, same
    deal — front-end only.

For each entry:
  1. HEAD-check every stored photo URL; flag any entry with >=1 dead photo.
  2. Re-resolve the place via Text Search (name + small location bias),
     requiring the result's cid (parsed from googleMapsUri) to match the
     stored cid exactly before trusting it — never silently substitutes a
     different business just because the name is similar.
  3. Fetch fresh Place Details + up to 3 new photo media URLs for confirmed
     matches.

Writes one report with three sections (csv / busan / clothing), each
{refreshed: {name: [urls]}, unmatched: {name: reason}}. Does NOT touch
index.html or the CSV directly — see splice_refreshed_photos.py for that,
run locally after reviewing the report.

Usage (CI): GOOGLE_PLACES_API_KEY=... python3 scripts/refresh_photo_urls.py
"""
import csv, io, json, os, re, time, urllib.request, urllib.error

INDEX_HTML_PATH = "index.html"
CSV_PATH = "supabase/restaurants-import.csv"
OUT_PATH = os.environ.get("REFRESH_PHOTOS_OUT_PATH", "candidate-results/photo-refresh-report.json")

KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
if not KEY:
    raise SystemExit("Missing GOOGLE_PLACES_API_KEY")

FIELD_MASK_SEARCH = ("places.id,places.displayName,places.formattedAddress,"
                      "places.googleMapsUri,places.location")
FIELD_MASK_DETAILS = "id,displayName,photos,googleMapsUri"


def search_text(query, lat, lng, radius=3000.0):
    url = "https://places.googleapis.com/v1/places:searchText"
    body = json.dumps({
        "textQuery": query, "languageCode": "zh-TW",
        "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius}}
    }).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST', headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": KEY, "X-Goog-FieldMask": FIELD_MASK_SEARCH,
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode('utf-8')}


def get_details(place_id):
    url = f"https://places.googleapis.com/v1/places/{place_id}?languageCode=zh-TW"
    req = urllib.request.Request(url, method='GET', headers={
        "X-Goog-Api-Key": KEY, "X-Goog-FieldMask": FIELD_MASK_DETAILS,
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode('utf-8'))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


opener = urllib.request.build_opener(NoRedirect)


def photo_url(photo_name, w=800, h=800):
    url = f"https://places.googleapis.com/v1/{photo_name}/media?maxWidthPx={w}&maxHeightPx={h}&key={KEY}"
    req = urllib.request.Request(url, method='GET')
    try:
        opener.open(req, timeout=20)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303):
            return e.headers.get('Location')
    return None


def head_ok(url):
    req = urllib.request.Request(url, method='HEAD')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def cid_of(maps_uri):
    m = re.search(r'cid=(\d+)', maps_uri or '')
    return m.group(1) if m else None


def parse_js_array(body):
    raw_entries = re.findall(r'\{name:"(?:[^"\\]|\\.)*".*?mapsUrl:"[^"]*"\}', body)
    entries = []
    for raw in raw_entries:
        name_m = re.search(r'name:"((?:[^"\\]|\\.)*)"', raw)
        lat_m = re.search(r'lat:([\-\d.]+)', raw)
        lng_m = re.search(r'lng:([\-\d.]+)', raw)
        photos_m = re.search(r'photos:\[(.*?)\]', raw)
        maps_m = re.search(r'mapsUrl:"([^"]*)"', raw)
        if not (name_m and lat_m and lng_m and maps_m):
            continue
        name = name_m.group(1).replace('\\"', '"').replace('\\\\', '\\')
        photos = re.findall(r'"([^"]*)"', photos_m.group(1)) if photos_m else []
        entries.append({
            'name': name, 'lat': float(lat_m.group(1)), 'lng': float(lng_m.group(1)),
            'photos': photos, 'mapsUrl': maps_m.group(1), 'cid': cid_of(maps_m.group(1)),
        })
    return entries


def parse_csv_rows(path):
    rows = list(csv.reader(open(path, encoding='utf-8')))
    header, data = rows[0], rows[1:]
    idx = {name: i for i, name in enumerate(header)}
    entries = []
    for row in data:
        photos_raw = row[idx['photos']]
        photos = []
        if photos_raw.startswith('{') and photos_raw.endswith('}'):
            photos = [p.strip('"').replace('\\"', '"').replace('\\\\', '\\')
                      for p in photos_raw[1:-1].split(',') if p]
        maps_url = row[idx['maps_url']]
        entries.append({
            'name': row[idx['name']], 'lat': float(row[idx['lat']]), 'lng': float(row[idx['lng']]),
            'photos': photos, 'mapsUrl': maps_url, 'cid': cid_of(maps_url),
        })
    return entries


def audit_and_refresh(entries, label):
    print(f"[{label}] {len(entries)} entries, {sum(len(e['photos']) for e in entries)} photo URLs to check")
    broken = []
    for i, e in enumerate(entries):
        dead = [p for p in e['photos'] if not head_ok(p)]
        if dead:
            broken.append(e)
        if (i + 1) % 50 == 0:
            print(f"[{label}]  checked {i+1}/{len(entries)}, {len(broken)} broken so far", flush=True)
    print(f"[{label}] {len(broken)}/{len(entries)} entries have >=1 dead photo URL")

    refreshed, unmatched = {}, {}
    for e in broken:
        data = search_text(e['name'], e['lat'], e['lng'])
        places = data.get('places', [])
        match = next((p for p in places if e['cid'] and cid_of(p.get('googleMapsUri', '')) == e['cid']), None)
        if not match:
            unmatched[e['name']] = f"no Text Search result matched cid={e['cid']}"
            continue
        try:
            d = get_details(match['id'])
        except Exception as ex:
            unmatched[e['name']] = f"Place Details fetch failed: {ex}"
            continue
        photos = d.get('photos', [])[:3]
        urls = []
        for ph in photos:
            u = photo_url(ph['name'])
            if u:
                urls.append(u)
            time.sleep(0.05)
        if not urls:
            unmatched[e['name']] = "re-matched place but it has zero photos now"
            continue
        refreshed[e['name']] = urls
        time.sleep(0.1)
        print(f"[{label}] refreshed: {e['name']} -> {len(urls)} photos")

    print(f"[{label}] refreshed {len(refreshed)}, unmatched {len(unmatched)}")
    return {'refreshed': refreshed, 'unmatched': unmatched}


html = open(INDEX_HTML_PATH, encoding='utf-8').read()

csv_entries = parse_csv_rows(CSV_PATH)

busan_m = re.search(r'const busanRestaurants = \[(.*?)\n\];', html, re.S)
busan_entries = parse_js_array(busan_m.group(1)) if busan_m else []

clothing_m = re.search(r'const taiwanClothingRestaurants = \[(.*?)\n\];', html, re.S)
clothing_entries = parse_js_array(clothing_m.group(1)) if clothing_m else []

report = {
    'csv': audit_and_refresh(csv_entries, 'csv'),
    'busan': audit_and_refresh(busan_entries, 'busan'),
    'clothing': audit_and_refresh(clothing_entries, 'clothing'),
}

os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
json.dump(report, open(OUT_PATH, 'w'), ensure_ascii=False, indent=1)
print("wrote", OUT_PATH)
