# -*- coding: utf-8 -*-
"""
Template: fetch full Place Details (photos, hours, phone, parking) for the
final picked list of restaurants.

EDIT PER TASK before running:
  - KEY_PATH, CANDIDATES_PATH, FINAL_LIST_PATH, OUT_PATH
  - FINAL_LIST_PATH should point to a JSON file you write by hand after
    picking the final restaurants from candidates.json, shaped like:
    {"新竹市": ["exact candidate name 1", "exact candidate name 2", ...],
     "竹北": [...]}
    Names must match exactly what's in candidates.json (the raw Google name,
    including any marketing suffix junk — you clean names up later in
    build_entries.py, not here).

Usage: python3 fetch_details.py
"""
import json, urllib.request, urllib.error, time

SB = "<YOUR_SCRATCHPAD_DIR>"  # EDIT
KEY_PATH = f"{SB}/gmaps_key.txt"
CANDIDATES_PATH = f"{SB}/candidates.json"
FINAL_LIST_PATH = f"{SB}/final_list.json"
OUT_PATH = f"{SB}/details.json"

KEY = open(KEY_PATH).read().strip()

candidates = json.load(open(CANDIDATES_PATH))
final_names_by_area = json.load(open(FINAL_LIST_PATH))
wanted = set()
for names in final_names_by_area.values():
    wanted |= set(names)
by_name = {v['name']: v for v in candidates.values()}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # lh3.googleusercontent.com is blocked in this sandbox but
    # places.googleapis.com is not — grab the redirect target from the
    # Location header without letting urllib follow it.
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
                  "nationalPhoneNumber,regularOpeningHours,parkingOptions,photos,"
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
json.dump(results, open(OUT_PATH, 'w'), ensure_ascii=False, indent=1)
