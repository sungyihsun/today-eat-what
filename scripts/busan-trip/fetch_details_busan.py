# -*- coding: utf-8 -*-
"""
One-off: fetch full Place Details (photos, hours, phone) for the final picked
list of Busan trip restaurants. Same technique as the add-restaurant skill's
fetch_details.py (NoRedirect photo-fetch pattern, Sunday=0->Monday=0 hours
conversion) but without the Taiwan-only AREA_KEYWORDS address safeguard.

FINAL_LIST_PATH: JSON written by the workflow's selection step, shaped like
{"西面": ["exact candidate name", ...], "海雲台": [...], ...}

Usage (CI): GOOGLE_PLACES_API_KEY=... python3 scripts/busan-trip/fetch_details_busan.py
"""
import json, os, urllib.request, urllib.error, time

CANDIDATES_PATH = os.environ.get("BUSAN_CANDIDATES_PATH", "candidate-results/busan-candidates.json")
FINAL_LIST_PATH = os.environ.get("BUSAN_FINAL_LIST_PATH", "candidate-results/busan-final-list.json")
OUT_PATH = os.environ.get("BUSAN_DETAILS_PATH", "candidate-results/busan-details.json")

KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
if not KEY:
    raise SystemExit("Missing GOOGLE_PLACES_API_KEY")

candidates = json.load(open(CANDIDATES_PATH))
final_names_by_area = json.load(open(FINAL_LIST_PATH))
wanted = set()
for names in final_names_by_area.values():
    wanted |= set(names)
by_name = {v['name']: v for v in candidates.values()}


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


def get_details(place_id):
    url = f"https://places.googleapis.com/v1/places/{place_id}"
    field_mask = ("id,displayName,formattedAddress,rating,userRatingCount,priceLevel,"
                  "nationalPhoneNumber,regularOpeningHours,photos,"
                  "primaryType,types,googleMapsUri,location")
    req = urllib.request.Request(url, method='GET', headers={
        "X-Goog-Api-Key": KEY, "X-Goog-FieldMask": field_mask,
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode('utf-8'))


def periods_to_hours(oh):
    """Google's day index is Sunday=0; this site uses Monday=0. Convert with
    (google_day + 6) % 7. A period crossing midnight gets its end pushed past
    1440 rather than wrapping."""
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


results = {}
missing = []
for name in wanted:
    rec = by_name.get(name)
    if not rec:
        missing.append(name)
        continue
    try:
        d = get_details(rec['place_id'])
    except Exception as e:
        print('ERROR', name, e)
        missing.append(name)
        continue
    photos = d.get('photos', [])[:3]
    photo_urls = []
    for ph in photos:
        u = photo_url(ph['name'])
        if u:
            photo_urls.append(u)
        time.sleep(0.05)
    d['_photo_urls'] = photo_urls
    d['_area_label'] = rec['area_label']
    d['_hoursweek'] = periods_to_hours(d.get('regularOpeningHours'))
    results[name] = d
    time.sleep(0.1)
    print('done:', name, '-> photos:', len(photo_urls), 'types:', d.get('types'))

print('missing:', missing)
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
json.dump(results, open(OUT_PATH, 'w'), ensure_ascii=False, indent=1)
