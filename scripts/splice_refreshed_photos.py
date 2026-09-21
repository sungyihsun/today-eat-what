# -*- coding: utf-8 -*-
"""
Apply candidate-results/photo-refresh-report.json (from refresh_photo_urls.py)
to index.html (embeddedRestaurants / busanRestaurants / taiwanClothingRestaurants)
and supabase/restaurants-import.csv. Only touches entries in the "refreshed"
section of each report bucket — "unmatched" entries are left alone and
printed so a human can look at them (usually means the business closed,
renamed, or moved on Google).

Usage: python3 scripts/splice_refreshed_photos.py
"""
import csv, io, json, re

REPORT_PATH = "candidate-results/photo-refresh-report.json"
INDEX_HTML_PATH = "index.html"
CSV_PATH = "supabase/restaurants-import.csv"

report = json.load(open(REPORT_PATH, encoding='utf-8'))


def js_arr(items):
    def esc(s):
        return s.replace('\\', '\\\\').replace('"', '\\"')
    return '[' + ','.join(f'"{esc(i)}"' for i in items) + ']'


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
            print(f"  WARNING: could not find entry for {name!r} in this array — skipped")
            continue
        body = new_body
        count += 1
    return before + body + after, count


html = open(INDEX_HTML_PATH, encoding='utf-8').read()

for label, marker in [('csv', None), ('busan', 'const busanRestaurants = ['),
                       ('clothing', 'const taiwanClothingRestaurants = [')]:
    if label == 'csv' or marker is None:
        continue
    refreshed = report.get(label, {}).get('refreshed', {})
    html, n = replace_photos_in_js_array(html, marker, refreshed)
    print(f"[{label}] updated {n}/{len(refreshed)} entries in index.html")

open(INDEX_HTML_PATH, 'w', encoding='utf-8').write(html)

# CSV: restaurants-import.csv rows correspond to embeddedRestaurants
# (Taiwan-only) entries — same names as report['csv'].
csv_refreshed = report.get('csv', {}).get('refreshed', {})
if csv_refreshed:
    rows = list(csv.reader(open(CSV_PATH, encoding='utf-8')))
    header, data = rows[0], rows[1:]
    photos_idx = header.index('photos')
    name_idx = header.index('name')
    updated = 0
    for row in data:
        if row[name_idx] in csv_refreshed:
            def esc(s):
                return s.replace('\\', '\\\\').replace('"', '\\"')
            urls = csv_refreshed[row[name_idx]]
            row[photos_idx] = '{' + ','.join(f'"{esc(u)}"' for u in urls) + '}'
            updated += 1
    out = io.StringIO()
    w = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator='\n')
    w.writerow(header)
    for row in data:
        w.writerow(row)
    open(CSV_PATH, 'w', encoding='utf-8').write(out.getvalue())
    print(f"[csv] updated {updated}/{len(csv_refreshed)} rows in {CSV_PATH}")

# Also need embeddedRestaurants (index.html's Taiwan fallback array) kept in
# sync with the same refreshed photos, since it's a separate array from the
# CSV even though both describe the same restaurants.
html = open(INDEX_HTML_PATH, encoding='utf-8').read()
html, n = replace_photos_in_js_array(html, 'const embeddedRestaurants = [', csv_refreshed)
print(f"[embeddedRestaurants] updated {n}/{len(csv_refreshed)} entries in index.html")
open(INDEX_HTML_PATH, 'w', encoding='utf-8').write(html)

for label in ('csv', 'busan', 'clothing'):
    unmatched = report.get(label, {}).get('unmatched', {})
    if unmatched:
        print(f"\n[{label}] UNMATCHED — needs manual attention:")
        for name, reason in unmatched.items():
            print(f"  - {name}: {reason}")
