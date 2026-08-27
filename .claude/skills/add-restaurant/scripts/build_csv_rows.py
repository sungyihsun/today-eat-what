# -*- coding: utf-8 -*-
"""
Template: turn details.json into CSV rows matching the exact column layout
and quoting rules of supabase/restaurants-import.csv, then append them.

THIS STEP IS THE ONE MOST LIKELY TO GET SKIPPED — don't skip it. See step 7
of SKILL.md for why: without this, new restaurants/categories work locally
but are silently unselectable on QAS/PRD because Supabase never got the data.

Keep CATS / NAME_OVERRIDE / TAGS_OVERRIDE in sync with whatever you used in
build_entries.py — they should produce the same names, cats, and tags, since
these two files describe the same restaurants for two different data stores.

EDIT PER TASK: same as build_entries.py, plus CSV_PATH.

Usage: python3 build_csv_rows.py
"""
import json, csv, io

SB = "<YOUR_SCRATCHPAD_DIR>"  # EDIT
DETAILS_PATH = f"{SB}/details.json"
CSV_PATH = "supabase/restaurants-import.csv"  # EDIT if running from a different cwd

CATS = ['健康餐']  # EDIT: keep in sync with build_entries.py

PRICE_MAP = {
    "PRICE_LEVEL_INEXPENSIVE": "$", "PRICE_LEVEL_MODERATE": "$$",
    "PRICE_LEVEL_EXPENSIVE": "$$$", "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$",
}

NAME_OVERRIDE = {
    # keep identical to build_entries.py's NAME_OVERRIDE
}
TAGS_OVERRIDE = {
    # keep identical to build_entries.py's TAGS_OVERRIDE
}


def parking_tier(po):
    if po is None:
        return ("unknown", None)
    lot = any(po.get(k) for k in (
        "freeParkingLot", "paidParkingLot", "freeGarageParking",
        "paidGarageParking", "valetParking"))
    street = any(po.get(k) for k in ("freeStreetParking", "paidStreetParking"))
    if lot:
        free = po.get('freeParkingLot') or po.get('freeGarageParking')
        return ("lot", "免費" if free else "付費")
    if street:
        free = po.get('freeStreetParking')
        return ("street", "免費" if free else "付費")
    return ("none", None)


details = json.load(open(DETAILS_PATH))

entries = []
for raw_name, d in details.items():
    name = NAME_OVERRIDE.get(raw_name, raw_name.strip())
    area_label = d['_area_label']
    loc = d.get('location', {})
    price = PRICE_MAP.get(d.get('priceLevel'), '$$')
    rating = d.get('rating', 0)
    count = d.get('userRatingCount', 0)
    catlabel = '、'.join(CATS)
    desc = f"{area_label}高評價{catlabel}，Google評分{rating}分、累積{count}則評論。"
    tier, sub = parking_tier(d.get('parkingOptions'))
    tags = TAGS_OVERRIDE.get(raw_name, [CATS[0], area_label, "高評價"])
    phone = (d.get('nationalPhoneNumber') or '').replace(' ', '-')
    entries.append({
        'name': name, 'area': area_label, 'lat': loc.get('latitude'), 'lng': loc.get('longitude'),
        'categories': list(CATS), 'price': price, 'rating': rating, 'description': desc, 'tags': tags,
        'phone': phone, 'parking_tier': tier, 'parking_sub': sub or '',
        'photos': d.get('_photo_urls', []), 'maps_url': d.get('googleMapsUri', ''),
        'hours': d.get('_hoursweek', [[] for _ in range(7)]),
    })


def pg_array(items):
    def esc(s):
        return s.replace('\\', '\\\\').replace('"', '\\"')
    return '{' + ','.join(f'"{esc(i)}"' for i in items) + '}'


rows = []
for e in entries:
    rows.append([
        e['name'], e['area'], e['lat'], e['lng'],
        pg_array(e['categories']), e['price'], e['rating'], e['description'],
        pg_array(e['tags']), e['phone'], e['parking_tier'], e['parking_sub'],
        pg_array(e['photos']), e['maps_url'],
        json.dumps(e['hours'], ensure_ascii=False, separators=(',', ':')),
    ])

out = io.StringIO()
w = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator='\n')
for r in rows:
    w.writerow(r)
append_text = out.getvalue()

existing = open(CSV_PATH, encoding='utf-8').read()
if not existing.endswith('\n'):
    raise SystemExit(f"{CSV_PATH} doesn't end with a newline — check the file before appending")
with open(CSV_PATH, 'w', encoding='utf-8') as f:
    f.write(existing + append_text)

print(f"appended {len(rows)} rows to {CSV_PATH}")

# Sanity-check with the *actual* parser logic (mirrors scripts/import-restaurants.mjs's
# parseCsv), not just Python's csv module, since that's what really runs in CI.
def parse_like_import_script(text):
    rows_out, row, value, quoted = [], [], '', False
    i = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ''
        if quoted and ch == '"' and nxt == '"':
            value += '"'; i += 2; continue
        if ch == '"':
            quoted = not quoted; i += 1; continue
        if not quoted and ch == ',':
            row.append(value); value = ''; i += 1; continue
        if not quoted and ch in '\r\n':
            if ch == '\r' and nxt == '\n':
                i += 1
            row.append(value)
            if any(row):
                rows_out.append(row)
            row, value = [], ''
            i += 1; continue
        value += ch; i += 1
    if value or row:
        row.append(value); rows_out.append(row)
    return rows_out

parsed = parse_like_import_script(open(CSV_PATH, encoding='utf-8').read())
header, data_rows = parsed[0], parsed[1:]
bad = [r for r in data_rows if len(r) != len(header)]
print(f"parsed {len(data_rows)} data rows, {len(bad)} with wrong column count (should be 0)")
if bad:
    raise SystemExit(f"CSV is malformed — first bad row starts with: {bad[0][0]!r}")
