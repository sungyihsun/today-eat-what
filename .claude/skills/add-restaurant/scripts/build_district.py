# -*- coding: utf-8 -*-
"""
Turn candidate-results/details.json into the site's data for ONE district:
appends to index.html (`let HOURS` + `const embeddedRestaurants`) AND
supabase/restaurants-import.csv, then enables/creates the area chip.

Usage (from repo root):
  python3 .claude/skills/add-restaurant/scripts/build_district.py CONFIG.json

CONFIG.json:
{
  "area": "南屯",                 # value stored in each entry's `area`
  "label": "南屯",                # chip text (defaults to area)
  "region": "中部",               # AREA_REGIONS group the chip belongs to
  "cats":  {raw_google_name: ["detailed cat string", ...]},   # REQUIRED for every name
  "names": {raw_google_name: "clean display name"},            # optional
  "tags":  {raw_google_name: ["tag", ...]},                    # optional
  "details": "candidate-results/details.json"                  # optional
}
Detailed cat strings must already exist in CAT_GROUPS_FOOD (index.html).
Refuses to write anything if a name/cid collides with existing data or a cat
string is unknown, and validates the CSV with the same parser logic the
Supabase import script uses.
"""
import csv, io, json, re, sys

INDEX = "index.html"
CSV_PATH = "supabase/restaurants-import.csv"

PRICE_MAP = {"PRICE_LEVEL_INEXPENSIVE": "$", "PRICE_LEVEL_MODERATE": "$$",
             "PRICE_LEVEL_EXPENSIVE": "$$$", "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$"}


def parking_tier(po):
    if po is None:
        return ("unknown", None)
    lot = any(po.get(k) for k in ("freeParkingLot", "paidParkingLot", "freeGarageParking",
                                  "paidGarageParking", "valetParking"))
    street = any(po.get(k) for k in ("freeStreetParking", "paidStreetParking"))
    if lot:
        return ("lot", "免費" if (po.get("freeParkingLot") or po.get("freeGarageParking")) else "付費")
    if street:
        return ("street", "免費" if po.get("freeStreetParking") else "付費")
    return ("none", None)


def js_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def js_arr(items):
    return "[" + ",".join(js_str(t) for t in items) + "]"


def js_hours(week):
    return "[" + ",".join("[" + ",".join(f"[{a},{b}]" for a, b in day) + "]" for day in week) + "]"


def pg_array(items):
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    return "{" + ",".join(f'"{esc(i)}"' for i in items) + "}"


def parse_like_import_script(text):
    rows, row, value, quoted, i = [], [], "", False, 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if quoted and ch == '"' and nxt == '"':
            value += '"'; i += 2; continue
        if ch == '"':
            quoted = not quoted; i += 1; continue
        if not quoted and ch == ",":
            row.append(value); value = ""; i += 1; continue
        if not quoted and ch in "\r\n":
            if ch == "\r" and nxt == "\n":
                i += 1
            row.append(value)
            if any(row):
                rows.append(row)
            row, value = [], ""
            i += 1; continue
        value += ch; i += 1
    if value or row:
        row.append(value); rows.append(row)
    return rows


def main(cfg_path):
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    area = cfg["area"]
    label = cfg.get("label", area)
    region = cfg.get("region", "中部")
    details = json.load(open(cfg.get("details", "candidate-results/details.json"), encoding="utf-8"))
    html = open(INDEX, encoding="utf-8").read()

    known_cats = set(re.findall(r"'([^']+)'", re.search(r"const CAT_GROUPS_FOOD = \{(.*?)\n\};", html, re.S).group(1)))
    existing_names = set(re.findall(r'\{name:"((?:[^"\\]|\\.)*)"', html))
    existing_cids = set(re.findall(r"cid=(\d+)", html))

    entries = []
    for raw, d in details.items():
        if raw not in cfg["cats"]:
            sys.exit(f"config has no cats for {raw!r}")
        cats = cfg["cats"][raw]
        bad = [c for c in cats if c not in known_cats]
        if bad:
            sys.exit(f"unknown cat string(s) {bad} for {raw!r} — must exist in CAT_GROUPS_FOOD")
        name = cfg.get("names", {}).get(raw, raw.strip())
        loc = d.get("location", {})
        rating, count = d.get("rating", 0), d.get("userRatingCount", 0)
        tier, sub = parking_tier(d.get("parkingOptions"))
        entries.append({
            "name": name, "area": area, "lat": loc.get("latitude"), "lng": loc.get("longitude"),
            "cat": cats, "price": PRICE_MAP.get(d.get("priceLevel"), "$$"), "rating": rating,
            "desc": f"{label}高評價{'、'.join(cats)}，Google評分{rating}分、累積{count}則評論。",
            "tags": cfg.get("tags", {}).get(raw, [cats[0], label, "高評價"]),
            "phone": (d.get("nationalPhoneNumber") or "").replace(" ", "-"),
            "parkingTier": tier, "parkingSub": sub,
            "photos": d.get("_photo_urls", []), "mapsUrl": d.get("googleMapsUri", ""),
            "hours": d.get("_hoursweek", [[] for _ in range(7)]),
        })

    seen = set()
    for e in entries:
        if e["name"] in seen:
            sys.exit(f"duplicate name within batch: {e['name']}")
        seen.add(e["name"])
        if e["name"] in existing_names:
            sys.exit(f"NAME COLLISION with existing site data: {e['name']}")
        m = re.search(r"cid=(\d+)", e["mapsUrl"])
        if m and m.group(1) in existing_cids:
            sys.exit(f"CID COLLISION with existing site data: {e['name']}")

    # ---- index.html ----
    hours_js = ",".join(f"{js_str(e['name'])}:{js_hours(e['hours'])}" for e in entries)
    lines = []
    for e in entries:
        parts = [f"name:{js_str(e['name'])}", f"area:{js_str(e['area'])}", f"lat:{e['lat']}", f"lng:{e['lng']}",
                 f"cat:{js_arr(e['cat'])}", f"price:{js_str(e['price'])}", f"rating:{e['rating']}",
                 f"desc:{js_str(e['desc'])}", f"tags:{js_arr(e['tags'])}", f"phone:{js_str(e['phone'])}",
                 f"parkingTier:{js_str(e['parkingTier'])}"]
        if e["parkingSub"]:
            parts.append(f"parkingSub:{js_str(e['parkingSub'])}")
        parts += [f"photos:{js_arr(e['photos'])}", f"mapsUrl:{js_str(e['mapsUrl'])}"]
        lines.append("  {" + ", ".join(parts) + "}")

    hs = html.index("let HOURS = {"); hc = html.index("};", hs) + 1
    assert html[hc - 3:hc] == "]]}", repr(html[hc - 3:hc])
    html = html[:hc - 1] + "," + hours_js + html[hc - 1:]
    es = html.index("const embeddedRestaurants = ["); ec = html.index("];", es) + 1
    assert html[ec - 3:ec] == "}\n]", repr(html[ec - 5:ec])
    html = html[:ec - 1] + ",\n" + ",\n".join(lines) + "\n" + html[ec - 1:]

    # area chip: flip a disabled placeholder, or add a new one to the region
    chip = re.search(r"\{area:'%s', label:'[^']*', enabled:(true|false)\}" % re.escape(area), html)
    if chip:
        html = html.replace(chip.group(0), chip.group(0).replace("enabled:false", "enabled:true"))
    else:
        rs = html.index("const AREA_REGIONS_TAIWAN = {")
        gs = html.index(f"'{region}': [", rs)
        ge = html.index("\n  ],", gs)
        html = html[:ge] + f"\n    {{area:'{area}', label:'{label}', enabled:true}}," + html[ge:]

    # ---- CSV ----
    existing = open(CSV_PATH, encoding="utf-8").read()
    if not existing.endswith("\n"):
        sys.exit(f"{CSV_PATH} does not end with a newline")
    out = io.StringIO()
    w = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\n")
    for e in entries:
        w.writerow([e["name"], e["area"], e["lat"], e["lng"], pg_array(e["cat"]), e["price"], e["rating"],
                    e["desc"], pg_array(e["tags"]), e["phone"], e["parkingTier"], e["parkingSub"] or "",
                    pg_array(e["photos"]), e["mapsUrl"],
                    json.dumps(e["hours"], ensure_ascii=False, separators=(",", ":"))])
    new_csv = existing + out.getvalue()
    parsed = parse_like_import_script(new_csv)
    bad_rows = [r for r in parsed[1:] if len(r) != len(parsed[0])]
    if bad_rows:
        sys.exit(f"CSV would be malformed — first bad row: {bad_rows[0][0]!r}")

    open(INDEX, "w", encoding="utf-8").write(html)
    open(CSV_PATH, "w", encoding="utf-8").write(new_csv)
    print(f"added {len(entries)} entries for area={area}; CSV now {len(parsed) - 1} data rows, 0 malformed")
    for e in entries:
        print(" ", e["name"], e["cat"], e["rating"], len(e["photos"]), "photos", e["parkingTier"])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
