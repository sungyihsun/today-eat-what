# -*- coding: utf-8 -*-
"""
Template: turn details.json into JS append fragments for index.html
(the `let HOURS = {...}` object and `const embeddedRestaurants = [...]` array),
after checking for name/cid collisions against the site's existing data.

EDIT PER TASK before running:
  - CATS: the detailed cat string(s) to tag every new entry with, e.g. ['健康餐']
    or a per-restaurant override if the category varies within the batch
  - NAME_OVERRIDE: raw Google name -> cleaned display name, for entries whose
    Google name has marketing junk ("｜訂位電話...", multi-branch spam, etc.)
  - TAGS_OVERRIDE: raw Google name -> custom tags array, for entries that
    deserve more specific tags than the generic [category, area, "高評價"]
  - INDEX_HTML_PATH: path to the site's index.html (for collision checking)

Run this AFTER fetch_details.py. If it raises "NAME COLLISION" or
"CID COLLISION", the restaurant is already in the site under a different
category — swap in a replacement candidate and re-run fetch_details.py for
just that one, rather than skipping the area short.

Usage: python3 build_entries.py
"""
import json, re

SB = "<YOUR_SCRATCHPAD_DIR>"  # EDIT
DETAILS_PATH = f"{SB}/details.json"
INDEX_HTML_PATH = "index.html"  # EDIT if running from a different cwd
HOURS_OUT = f"{SB}/hours_append.txt"
RESTAURANTS_OUT = f"{SB}/restaurants_append.txt"

CATS = ['健康餐']  # EDIT: detailed cat string(s) for this batch

PRICE_MAP = {
    "PRICE_LEVEL_INEXPENSIVE": "$", "PRICE_LEVEL_MODERATE": "$$",
    "PRICE_LEVEL_EXPENSIVE": "$$$", "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$",
}

NAME_OVERRIDE = {
    # "raw Google name with junk": "Clean Display Name",
}
TAGS_OVERRIDE = {
    # "raw Google name": ["custom", "tags", "here"],
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
        'cat': list(CATS), 'price': price, 'rating': rating, 'desc': desc, 'tags': tags,
        'phone': phone, 'parkingTier': tier, 'parkingSub': sub,
        'photos': d.get('_photo_urls', []), 'mapsUrl': d.get('googleMapsUri', ''),
        '_hoursweek': d.get('_hoursweek', [[] for _ in range(7)]),
    })

print('total entries:', len(entries))

names_seen = set()
for e in entries:
    if e['name'] in names_seen:
        raise SystemExit(f"INTERNAL DUP NAME: {e['name']}")
    names_seen.add(e['name'])

html = open(INDEX_HTML_PATH, encoding='utf-8').read()
existing_names = set(re.findall(r'\{name:"((?:[^"\\]|\\.)*)"', html))
existing_cids = set(re.findall(r'cid=(\d+)', html))
for e in entries:
    if e['name'] in existing_names:
        raise SystemExit(f"NAME COLLISION WITH EXISTING SITE: {e['name']} — pick a replacement candidate")
    cid_m = re.search(r'cid=(\d+)', e['mapsUrl'])
    if cid_m and cid_m.group(1) in existing_cids:
        raise SystemExit(f"CID COLLISION: {e['name']} — pick a replacement candidate")
print("no collisions with existing site data — OK")


def js_str(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def js_arr(items):
    return '[' + ','.join(js_str(t) for t in items) + ']'


def js_hours_val(week):
    return '[' + ','.join('[' + ','.join(f'[{a},{b}]' for a, b in day) + ']' for day in week) + ']'


hours_parts = [f"{js_str(e['name'])}:{js_hours_val(e['_hoursweek'])}" for e in entries]
hours_append_js = ",".join(hours_parts)

entry_lines = []
for e in entries:
    parts = [
        f"name:{js_str(e['name'])}", f"area:{js_str(e['area'])}",
        f"lat:{e['lat']}", f"lng:{e['lng']}",
        f"cat:{js_arr(e['cat'])}",
        f"price:{js_str(e['price'])}", f"rating:{e['rating']}", f"desc:{js_str(e['desc'])}",
        f"tags:{js_arr(e['tags'])}", f"phone:{js_str(e['phone'] or '')}",
        f"parkingTier:{js_str(e['parkingTier'])}",
    ]
    if e.get('parkingSub'):
        parts.append(f"parkingSub:{js_str(e['parkingSub'])}")
    parts.append(f"photos:{js_arr(e['photos'])}")
    parts.append(f"mapsUrl:{js_str(e['mapsUrl'])}")
    entry_lines.append("  {" + ", ".join(parts) + "}")

restaurants_append_js = ",\n".join(entry_lines)
open(HOURS_OUT, 'w', encoding='utf-8').write(hours_append_js)
open(RESTAURANTS_OUT, 'w', encoding='utf-8').write(restaurants_append_js)
print('wrote', HOURS_OUT, 'and', RESTAURANTS_OUT)
print()
print("NEXT: splice these into index.html —")
print("  1. In `let HOURS = {...}`, insert the contents of hours_append.txt")
print("     right before the closing `};`, preceded by a comma.")
print("  2. In `const embeddedRestaurants = [...]`, insert the contents of")
print("     restaurants_append.txt right before the closing `];`.")
print("  In BOTH cases, check whether the entry immediately before your")
print("  insertion point already ends with a comma — if not, add one first,")
print("  or node --check will fail on the first line of your new data.")

for e in entries:
    print(e['name'], '|', e['area'], '|', e['rating'], '|', len(e['photos']), 'photos', '|', e['parkingTier'])
