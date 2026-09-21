# -*- coding: utf-8 -*-
"""
Apply candidate-results/monthly-audit-report.json (from monthly_data_audit.py)
to index.html (embeddedRestaurants/busanRestaurants/taiwanClothingRestaurants
+ their HOURS objects) and supabase/restaurants-import.csv.

Only touches entries with photos_refreshed or hours_changed set. Businesses
Google now reports as not OPERATIONAL are NEVER auto-removed — this only
prints them so a human decides whether to delete the listing. "unmatched"
entries (Text Search couldn't confirm the same cid) are left alone too and
printed for the same reason — could be renamed, moved, or a transient
Google-side hiccup.

Usage: python3 scripts/apply_monthly_audit.py
"""
import csv, io, json, re

REPORT_PATH = "candidate-results/monthly-audit-report.json"
INDEX_HTML_PATH = "index.html"
CSV_PATH = "supabase/restaurants-import.csv"

report = json.load(open(REPORT_PATH, encoding='utf-8'))


def js_arr(items):
    def esc(s):
        return s.replace('\\', '\\\\').replace('"', '\\"')
    return '[' + ','.join(f'"{esc(i)}"' for i in items) + ']'


def js_hours_val(week):
    return '[' + ','.join('[' + ','.join(f'[{a},{b}]' for a, b in day) + ']' for day in week) + ']'


def photos_to_update(entries_report):
    return {name: v['new_photos'] for name, v in entries_report.items() if v.get('photos_refreshed')}


def hours_to_update(entries_report):
    return {name: v['new_hours'] for name, v in entries_report.items() if v.get('hours_changed')}


def replace_photos_in_js_array(html, array_start_marker, refreshed):
    if not refreshed:
        return html, 0
    start = html.index(array_start_marker)
    close_idx = html.index('\n];', start)
    before, body, after = html[:start], html[start:close_idx], html[close_idx:]
    count = 0
    for name, urls in refreshed.items():
        name_esc = name.replace('\\', '\\\\').replace('"', '\\"')
        pattern = re.compile(r'(\{name:"' + re.escape(name_esc) + r'".*?photos:)\[.*?\](.*?mapsUrl:)', re.S)
        new_body, n = pattern.subn(lambda m: m.group(1) + js_arr(urls) + m.group(2), body, count=1)
        if n == 0:
            print(f"  WARNING: could not find entry for {name!r} to update photos — skipped")
            continue
        body = new_body
        count += 1
    return before + body + after, count


def replace_hours_in_object(html, var_decl, updates):
    if not updates:
        return html, 0
    start = html.index(var_decl)
    close_idx = html.index('};', start) + 1  # keep the trailing ';'
    before, body, after = html[:start], html[start:close_idx - 1], html[close_idx - 1:]
    count = 0
    for name, hours in updates.items():
        name_esc = name.replace('\\', '\\\\').replace('"', '\\"')
        key = f'"{name_esc}":'
        key_idx = body.find(key)
        if key_idx == -1:
            print(f"  WARNING: could not find hours entry for {name!r} — skipped")
            continue
        # The value is a bracketed array; non-greedy regex would stop at the
        # first ']' it hits (e.g. an empty day-0 array like "[]" right after
        # the opening bracket), corrupting the rest of the week — walk
        # bracket depth manually to find the real end instead.
        val_start = key_idx + len(key)
        depth = 0
        val_end = None
        for i in range(val_start, len(body)):
            if body[i] == '[':
                depth += 1
            elif body[i] == ']':
                depth -= 1
                if depth == 0:
                    val_end = i + 1
                    break
        if val_end is None:
            print(f"  WARNING: unbalanced brackets while parsing hours for {name!r} — skipped")
            continue
        body = body[:val_start] + js_hours_val(hours) + body[val_end:]
        count += 1
    return before + body + after, count


html = open(INDEX_HTML_PATH, encoding='utf-8').read()

for label, marker, hours_marker in [
    ('busan', 'const busanRestaurants = [', 'const BUSAN_HOURS = '),
    ('clothing', 'const taiwanClothingRestaurants = [', 'const TAIWAN_CLOTHING_HOURS = '),
]:
    sec = report.get(label, {}).get('entries', {})
    html, n = replace_photos_in_js_array(html, marker, photos_to_update(sec))
    print(f"[{label}] updated photos for {n} entries in index.html")
    html, n2 = replace_hours_in_object(html, hours_marker, hours_to_update(sec))
    print(f"[{label}] updated hours for {n2} entries in index.html")

csv_sec = report.get('csv', {}).get('entries', {})
csv_photo_updates = photos_to_update(csv_sec)
csv_hours_updates = hours_to_update(csv_sec)

if csv_photo_updates or csv_hours_updates:
    html, n = replace_photos_in_js_array(html, 'const embeddedRestaurants = [', csv_photo_updates)
    print(f"[embeddedRestaurants] updated photos for {n} entries in index.html")
    html, n2 = replace_hours_in_object(html, 'let HOURS = ', csv_hours_updates)
    print(f"[HOURS] updated hours for {n2} entries in index.html")

open(INDEX_HTML_PATH, 'w', encoding='utf-8').write(html)

if csv_photo_updates or csv_hours_updates:
    rows = list(csv.reader(open(CSV_PATH, encoding='utf-8')))
    header, data = rows[0], rows[1:]
    photos_idx = header.index('photos')
    hours_idx = header.index('hours')
    name_idx = header.index('name')

    def esc(s):
        return s.replace('\\', '\\\\').replace('"', '\\"')

    updated = 0
    for row in data:
        name = row[name_idx]
        changed = False
        if name in csv_photo_updates:
            urls = csv_photo_updates[name]
            row[photos_idx] = '{' + ','.join(f'"{esc(u)}"' for u in urls) + '}'
            changed = True
        if name in csv_hours_updates:
            row[hours_idx] = json.dumps(csv_hours_updates[name], ensure_ascii=False, separators=(',', ':'))
            changed = True
        if changed:
            updated += 1
    out = io.StringIO()
    w = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator='\n')
    w.writerow(header)
    for row in data:
        w.writerow(row)
    open(CSV_PATH, 'w', encoding='utf-8').write(out.getvalue())
    print(f"[csv] updated {updated} rows in {CSV_PATH}")

print()
for label in ('csv', 'busan', 'clothing'):
    sec = report.get(label, {})
    closed = {name: v['business_status'] for name, v in sec.get('entries', {}).items()
              if v['business_status'] != 'OPERATIONAL'}
    if closed:
        print(f"[{label}] NOT OPERATIONAL — review and remove manually if confirmed closed:")
        for name, status in closed.items():
            print(f"  - {name}: {status}")
    unmatched = sec.get('unmatched', {})
    if unmatched:
        print(f"[{label}] UNMATCHED — needs manual attention:")
        for name, reason in unmatched.items():
            print(f"  - {name}: {reason}")
