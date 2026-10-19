# -*- coding: utf-8 -*-
"""
旅遊版（trip mode）城市資料：把 candidate-results/details.json 寫進 index.html 裡
該城市專屬的資料陣列與營業時間表（例如 fukuokaRestaurants / FUKUOKA_HOURS）。
旅遊版資料只存在前端，**不進 Supabase／CSV**（跟釜山一樣）。

Usage (repo root):  python3 .claude/skills/add-restaurant/scripts/build_trip_city.py CONFIG.json

CONFIG.json:
{
  "array":   "fukuokaRestaurants",          # index.html 裡的 const 陣列名稱
  "hours":   "FUKUOKA_HOURS",               # index.html 裡的 const 營業時間物件名稱
  "centers": {"博多": [lat, lng], ...},      # 商圈中心；每家店的 area = 距離最近的商圈
  "entries": {                              # key = details.json 裡的 Google 原名
     "<raw name>": {"zh": "中文名", "cats": ["細分類"], "tags": ["標籤"], "name": "（選填）去掉雜訊的原名",
                    "area": "（選填）強制 area，例如近郊一日遊景點", "transport": {"mode": "地鐵", "note": "…"}}
  },
  "skip": ["raw name", ...],               # 選填：details 裡有但不收錄
  "details": "candidate-results/details.json"   # 選填；可為檔案路徑陣列（依序合併）
}

語意是「整批取代」：每次執行都會用這份 config 重建該陣列與營業時間表（可重複執行）。
停車欄位用 Place Details 的真實資料（lot／street／none／unknown）——日本是自駕，
不像釜山一律 walk。遇到未知分類、重複店名/cid、缺 config 時直接退出且不寫檔。
"""
import json, math, re, sys

INDEX = "index.html"
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


def hav(a, b):
    R = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def js_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def js_arr(items):
    return "[" + ",".join(js_str(t) for t in items) + "]"


def js_hours(week):
    return "[" + ",".join("[" + ",".join(f"[{a},{b}]" for a, b in day) + "]" for day in week) + "]"


def main(cfg_path):
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    srcs = cfg.get("details", "candidate-results/details.json")
    details = {}
    for src in ([srcs] if isinstance(srcs, str) else srcs):
        details.update(json.load(open(src, encoding="utf-8")))
    html = open(INDEX, encoding="utf-8").read()
    known = set()
    for const in ("CAT_GROUPS_FOOD", "CAT_GROUPS_FUKUOKA"):
        m = re.search(r"const %s = \{(.*?)\n\};" % const, html, re.S)
        if m:
            known |= set(re.findall(r"'([^']+)'", m.group(1)))

    skip = set(cfg.get("skip", []))  # 刻意不收錄的店（details 裡有但不上站）
    details = {k: v for k, v in details.items() if k not in skip}
    missing = [n for n in details if n not in cfg["entries"]]
    if missing:
        sys.exit(f"config has no entry for: {missing[:5]}")

    entries, seen_names, seen_cids = [], set(), set()
    for raw, d in details.items():
        c = cfg["entries"][raw]
        bad = [x for x in c["cats"] if x not in known]
        if bad:
            sys.exit(f"unknown cat(s) {bad} for {raw!r} — must exist in CAT_GROUPS_FOOD")
        name = c.get("name", raw.strip())
        if name in seen_names:
            sys.exit(f"duplicate name in batch: {name}")
        seen_names.add(name)
        cid = (re.search(r"cid=(\d+)", d.get("googleMapsUri", "")) or [None, None])[1]
        if cid and cid in seen_cids:
            sys.exit(f"duplicate cid in batch: {name}")
        seen_cids.add(cid)
        loc = d["location"]
        pos = (loc["latitude"], loc["longitude"])
        area = c.get("area") or min(cfg["centers"], key=lambda k: hav(pos, cfg["centers"][k]))
        tier, sub = parking_tier(d.get("parkingOptions"))
        rating, count = d.get("rating", 0), d.get("userRatingCount", 0)
        cats = c["cats"]
        kind = "景點" if cats == ["景點"] else ("逛街景點" if "逛街" in cats else "、".join(cats))
        price = PRICE_MAP.get(d.get("priceLevel")) or ("$" if "景點" in cats else "$$")
        entries.append({
            "name": name, "nameZh": c["zh"], "area": area, "lat": pos[0], "lng": pos[1], "cat": cats,
            "price": price, "rating": rating, "desc": f"{area}高評價{kind}，Google評分{rating}分、累積{count}則評論。",
            "tags": c["tags"], "phone": (d.get("nationalPhoneNumber") or "").replace(" ", "-"),
            "parkingTier": tier, "parkingSub": sub, "photos": d.get("_photo_urls", []),
            "mapsUrl": d.get("googleMapsUri", ""), "hours": d.get("_hoursweek", [[] for _ in range(7)]),
            "transport": c.get("transport"),
        })

    lines = []
    for e in entries:
        parts = [f"name:{js_str(e['name'])}", f"nameZh:{js_str(e['nameZh'])}", f"area:{js_str(e['area'])}",
                 f"lat:{e['lat']}", f"lng:{e['lng']}", f"cat:{js_arr(e['cat'])}", f"price:{js_str(e['price'])}",
                 f"rating:{e['rating']}", f"desc:{js_str(e['desc'])}", f"tags:{js_arr(e['tags'])}",
                 f"phone:{js_str(e['phone'])}", f"parkingTier:{js_str(e['parkingTier'])}"]
        if e["parkingSub"]:
            parts.append(f"parkingSub:{js_str(e['parkingSub'])}")
        if e["transport"]:
            parts.append(f"transport:{{mode:{js_str(e['transport']['mode'])},note:{js_str(e['transport']['note'])}}}")
        parts += [f"photos:{js_arr(e['photos'])}", f"mapsUrl:{js_str(e['mapsUrl'])}"]
        lines.append("  {" + ", ".join(parts) + "}")
    hours_obj = "{" + ",".join(f"{js_str(e['name'])}:{js_hours(e['hours'])}" for e in entries) + "}"

    arr_re = re.compile(r"(const %s = \[)(.*?)(\n\];)" % re.escape(cfg["array"]), re.S)
    hrs_re = re.compile(r"const %s = \{.*?\};" % re.escape(cfg["hours"]))
    if len(arr_re.findall(html)) != 1 or len(hrs_re.findall(html)) != 1:
        sys.exit("array/hours markers not found exactly once in index.html")
    html = arr_re.sub(lambda m: m.group(1) + "\n" + ",\n".join(lines) + m.group(3), html, count=1)
    html = hrs_re.sub(lambda m: f"const {cfg['hours']} = {hours_obj};", html, count=1)
    open(INDEX, "w", encoding="utf-8").write(html)

    by_area = {}
    for e in entries:
        by_area[e["area"]] = by_area.get(e["area"], 0) + 1
    print(f"wrote {len(entries)} entries to {cfg['array']}; by area: {by_area}")
    print("parking:", {t: sum(1 for e in entries if e['parkingTier'] == t) for t in ('lot', 'street', 'none', 'unknown')})


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
