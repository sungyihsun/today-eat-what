# -*- coding: utf-8 -*-
"""
Monthly maintenance audit. For every restaurant/campsite-style entry in the
site's three data sources:
  - supabase/restaurants-import.csv (canonical for Taiwan 新竹/竹北/桃園 —
    this is what QAS/PRD actually serve via Supabase, NOT embeddedRestaurants,
    which is only the DEV/offline fallback array)
  - index.html's `const busanRestaurants = [...]` (旅遊版/釜山, front-end only)
  - index.html's `const taiwanClothingRestaurants = [...]` (服飾, front-end only)

...does THREE checks against live Google Places data:
  1. Photo URLs: Google's Place Photo media URLs are signed/ephemeral and
     expire after some weeks. HEAD-check every stored photo URL; refresh any
     that are dead.
  2. Business status: flag anything Google now reports as
     CLOSED_TEMPORARILY / CLOSED_PERMANENTLY. Never auto-removes — closing a
     listing is a judgment call for a human, this only flags it.
  3. Opening hours: re-fetch regularOpeningHours and compare (after
     conversion to this site's Monday=0 minute-range format) against what's
     currently stored. Flags + stages an update if it changed.

Every entry is re-resolved via Text Search (name + small location bias)
first, requiring the result's cid (parsed from googleMapsUri) to match the
stored cid exactly — never silently substitutes a different business just
because the name is similar. No match -> reported unmatched, left alone.

Writes one report with three sections (csv / busan / clothing), each:
  {
    "entries": {name: {business_status, hours_changed, new_hours, photos_refreshed, new_photos}},
    "unmatched": {name: reason}
  }
Does NOT touch index.html or the CSV directly — see apply_monthly_audit.py.

Usage (CI): GOOGLE_PLACES_API_KEY=... python3 scripts/monthly_data_audit.py
"""
import csv, json, os, re, time, urllib.request, urllib.error

INDEX_HTML_PATH = "index.html"
CSV_PATH = "supabase/restaurants-import.csv"
OUT_PATH = os.environ.get("MONTHLY_AUDIT_OUT_PATH", "candidate-results/monthly-audit-report.json")

KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
if not KEY:
    raise SystemExit("Missing GOOGLE_PLACES_API_KEY")

FIELD_MASK_SEARCH = ("places.id,places.displayName,places.formattedAddress,"
                      "places.googleMapsUri,places.location")
FIELD_MASK_DETAILS = "id,displayName,photos,googleMapsUri,businessStatus,regularOpeningHours"


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


def periods_to_hours(oh):
    """Google's day index is Sunday=0; this site uses Monday=0. Convert with
    (google_day + 6) % 7. A period crossing midnight gets its end pushed past
    1440 rather than wrapping. Same logic as the add-restaurant skill's
    fetch_details.py — keep in sync."""
    week = [[] for _ in range(7)]
    periods = (oh or {}).get('periods')
    if not periods:
        return week

    def gidx_to_midx(gday):
        return (gday + 6) % 7

    for p in periods:
        o = p.get('open')
        c = p.get('close')
        if not o or not c:
            continue
        oday = gidx_to_midx(o['day'])
        omin = o['hour'] * 60 + o['minute']
        cday = gidx_to_midx(c['day'])
        cmin = c['hour'] * 60 + c['minute']
        end = (cmin if cmin > omin else cmin + 1440) if cday == oday else cmin + 1440
        week[oday].append([omin, end])
    for d in week:
        d.sort()
    return week


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


def parse_hours_object(html, var_decl):
    m = re.search(re.escape(var_decl) + r'(\{.*?\});', html, re.S)
    if not m:
        return {}
    return json.loads(m.group(1))


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
        hours = json.loads(row[idx['hours']]) if row[idx['hours']] else []
        entries.append({
            'name': row[idx['name']], 'lat': float(row[idx['lat']]), 'lng': float(row[idx['lng']]),
            'photos': photos, 'mapsUrl': maps_url, 'cid': cid_of(maps_url), 'hours': hours,
        })
    return entries


def audit(entries, label):
    print(f"[{label}] {len(entries)} entries to audit")
    result_entries, unmatched = {}, {}
    for i, e in enumerate(entries):
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

        entry_report = {'business_status': d.get('businessStatus', 'UNKNOWN')}

        new_hours = periods_to_hours(d.get('regularOpeningHours'))
        old_hours = e.get('hours', [])
        if new_hours != old_hours:
            entry_report['hours_changed'] = True
            entry_report['old_hours'] = old_hours
            entry_report['new_hours'] = new_hours
        else:
            entry_report['hours_changed'] = False

        dead = [p for p in e['photos'] if not head_ok(p)]
        if dead:
            photos = d.get('photos', [])[:3]
            urls = []
            for ph in photos:
                u = photo_url(ph['name'])
                if u:
                    urls.append(u)
                time.sleep(0.05)
            if urls:
                entry_report['photos_refreshed'] = True
                entry_report['new_photos'] = urls
            else:
                entry_report['photos_refreshed'] = False
        else:
            entry_report['photos_refreshed'] = False

        result_entries[e['name']] = entry_report
        time.sleep(0.1)
        if (i + 1) % 50 == 0:
            print(f"[{label}]  processed {i+1}/{len(entries)}", flush=True)

    n_closed = sum(1 for v in result_entries.values() if v['business_status'] != 'OPERATIONAL')
    n_hours = sum(1 for v in result_entries.values() if v['hours_changed'])
    n_photos = sum(1 for v in result_entries.values() if v.get('photos_refreshed'))
    print(f"[{label}] done: {n_closed} not operational, {n_hours} hours changed, "
          f"{n_photos} photos refreshed, {len(unmatched)} unmatched")
    return {'entries': result_entries, 'unmatched': unmatched}


html = open(INDEX_HTML_PATH, encoding='utf-8').read()

csv_entries = parse_csv_rows(CSV_PATH)

busan_m = re.search(r'const busanRestaurants = \[(.*?)\n\];', html, re.S)
busan_entries = parse_js_array(busan_m.group(1)) if busan_m else []
busan_hours = parse_hours_object(html, 'const BUSAN_HOURS = ')
for e in busan_entries:
    e['hours'] = busan_hours.get(e['name'], [])

clothing_m = re.search(r'const taiwanClothingRestaurants = \[(.*?)\n\];', html, re.S)
clothing_entries = parse_js_array(clothing_m.group(1)) if clothing_m else []
clothing_hours = parse_hours_object(html, 'const TAIWAN_CLOTHING_HOURS = ')
for e in clothing_entries:
    e['hours'] = clothing_hours.get(e['name'], [])

report = {
    'csv': audit(csv_entries, 'csv'),
    'busan': audit(busan_entries, 'busan'),
    'clothing': audit(clothing_entries, 'clothing'),
}

os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
json.dump(report, open(OUT_PATH, 'w'), ensure_ascii=False, indent=1)
print("wrote", OUT_PATH)
