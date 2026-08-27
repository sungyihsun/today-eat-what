---
name: add-restaurant
description: Add new restaurants (or a new category of restaurants) to the "今天吃什麼" / today-eat-what site — searching Google Places, building entries, and deploying through DEV → QAS → PRD. Use this whenever the user asks to add restaurants for an area (e.g. "新竹市/竹北各新增N家"), add a new food category with real restaurant data, or expand coverage to a new city/district. This is an internal operating checklist distilled from a session that actually ran this workflow several times and hit real bugs — follow it exactly rather than improvising the data pipeline from scratch, especially the Supabase sync step, which is easy to forget and silently breaks the QAS/PRD site.
---

# 新增餐廳 (Add Restaurant)

This skill captures the exact, validated pipeline for adding restaurants to this
site: search → dedupe → fetch details → splice into both data stores → validate →
deploy DEV → QAS → PRD. Every step here exists because skipping it caused a real
bug earlier in this project — read the "why" behind each one, don't just follow it
mechanically, in case something about the codebase has since changed.

## 0. Orient yourself first

Before touching anything, confirm:

- `git branch --show-current` — start every task on `DEV`. If not there,
  `git checkout DEV && git pull origin DEV`.
- `git status --short` — should be clean. If not, figure out what's there before
  overwriting anything (see the git-safety rules in your system prompt).
- The site's data model may have evolved since this skill was written. Re-read
  the current `CAT_GROUPS` / `SUB_CAT_GROUPS` block in `index.html` (search for
  `const CAT_GROUPS`) before assuming a category exists or picking a label.

## 1. Get the API key, scoped and disposable

Ask the user to paste their Google Places API key if not already provided this
session. Treat it like any other secret:

```bash
SB=<your scratchpad dir>
mkdir -p "$SB"
echo -n "<key>" > "$SB/gmaps_key.txt"
```

Never write the key into any file inside the repo, never put it in a commit
message. Delete `$SB/gmaps_key.txt` with `rm -f` the moment you're done fetching
data — not at the end of the whole task, right after the last API call.

## 2. Search candidates via Text Search

Use the Places API (New) `searchText` endpoint, biased to the target area's
lat/lng with `locationBias.circle`, `languageCode: "zh-TW"`. Run a few query
variants per area (e.g. for a "健康餐" category: `"健康餐 新竹市"`,
`"波奇碗 新竹市"`, `"沙拉專賣 新竹市"`, `"輕食 新竹市"`) — one query alone
tends to miss real candidates. Field mask should include at least:
`id,displayName,formattedAddress,rating,userRatingCount,priceLevel,googleMapsUri,location,types`.

Filter candidates to `rating >= 4.0` and a sane minimum review count (15–20 is
reasonable) so you're not recommending places with barely any signal. Dedupe
candidates across query variants by the `cid` parsed out of `googleMapsUri`
(`re.search(r'cid=(\d+)', uri)`).

Reference implementation: `scripts/search_candidates.py` in this skill directory
— adapt the query list and area coordinates per task, don't rewrite it from
scratch each time.

## 3. Pick the final list, then dedupe against the site itself

Eyeball the candidates and pick the requested count per area, biasing toward:
- Higher rating + higher review count (both matter — a 5.0 with 12 reviews is
  less trustworthy than a 4.6 with 800)
- Genuine restaurants over adjacent business types (Google's `types` field
  sometimes returns hair salons for "波奇/洗頭" style false positives, gyms,
  grocery stores — check `types` before trusting a result)
- If the task asks for a specific dish/style to be represented (e.g. "包含波奇"),
  make sure at least a few final picks are actually that dish, not just
  generically in the category

Before fetching full details, **cross-check every candidate's `cid` and exact
name against the site's existing data** — this project has repeatedly hit name
collisions where a candidate is already in the database under a different
category:

```bash
python3 -c "
import re
html = open('index.html', encoding='utf-8').read()
existing_names = set(re.findall(r'\{name:\"((?:[^\"\\\\\\\\]|\\\\\\\\.)*)\"', html))
existing_cids = set(re.findall(r'cid=(\d+)', html))
print('検collision check ready:', len(existing_names), 'names,', len(existing_cids), 'cids')
"
```

If a pick collides, swap in the next-best candidate rather than skipping the
area short — the user is expecting an exact count per area.

## 4. Fetch full details (photos, hours, phone, parking)

For each final pick, call Place Details with field mask:
`id,displayName,formattedAddress,rating,userRatingCount,priceLevel,nationalPhoneNumber,regularOpeningHours,parkingOptions,photos,primaryType,types,googleMapsUri,location`.

For photos: `lh3.googleusercontent.com` is blocked in this sandbox, but
`places.googleapis.com` is not. Fetch the photo media endpoint with a redirect
handler that captures the `Location` header from the 302 without following it
(see `scripts/fetch_details.py` — the `NoRedirect` handler pattern). Take up to
3 photos per restaurant.

Convert `regularOpeningHours.periods` into this site's hours format: an array
of 7 day-arrays (Monday=0 … Sunday=6), each containing `[startMinute,
endMinute]` pairs. **Google's day index is Sunday=0** — convert with
`(google_day + 6) % 7` to get this site's Monday=0 indexing. A period that
crosses midnight needs its end minute pushed past 1440 rather than wrapping to
a small number (see `periods_to_hours` in `scripts/fetch_details.py`).

## 5. Categorize using detailed cat strings, not UI labels

The site's category filter (`CAT_GROUPS` / `SUB_CAT_GROUPS` in `index.html`) is
a *grouping* layer: each UI chip label (e.g. `'健康餐'`, `'越式'`) maps to one
or more **detailed cat strings** that actually live on each restaurant's `cat`
array (e.g. `'健康餐'`, `'越式料理'`). When you add restaurants for an existing
category, use the exact detailed string(s) already in `CAT_GROUPS` for that
label — check the mapping before writing entries. When adding a *new* category
that doesn't exist yet, you'll also need to add it to `CAT_GROUPS` (see step 8).

A restaurant can carry multiple cat strings if it genuinely spans categories
(e.g. a buffet hotpot place is `["火鍋/鍋物", "吃到飽"]`) — don't force
single-category tagging if the place doesn't fit that.

## 6. Build the JS entries and splice into `index.html`

Generate entries in this exact shape (see `scripts/build_entries.py` for the
full generator, including price-level mapping, parking-tier detection, and the
auto-generated `desc`/`tags` fields):

```js
{name:"...", area:"...", lat:..., lng:..., cat:["..."], price:"$$", rating:4.5,
 desc:"...", tags:["...","...","..."], phone:"...", parkingTier:"lot",
 parkingSub:"付費", photos:["...","...","..."], mapsUrl:"..."}
```

Then splice into **two places** in `index.html`:

1. `let HOURS = {...}` — a single-line object literal. Insert your new
   `"name":[[...],[...],...]` pairs right before the closing `};`.
2. `const embeddedRestaurants = [...]` — insert your new entry objects right
   before the closing `];`.

**Watch for the missing-trailing-comma trap**: the existing last entry in each
of these often does *not* end with a comma (because it used to be the last
one). Check the character right before your insertion point and add a comma if
needed, or `node --check` will fail with a cryptic `Unexpected token '{'` at
the first line of your new data — this has happened almost every time this
skill's workflow has run.

## 7. THE STEP THAT'S EASY TO FORGET: update `supabase/restaurants-import.csv`

**This is the single most important step in this skill, and it has caused a
real, user-reported bug when skipped.** The QAS and PRD sites don't read
`embeddedRestaurants` from `index.html` in normal operation — they fetch from
a Supabase `restaurants` table at load time, and only fall back to the
embedded array if that fetch fails. `embeddedRestaurants` is *only* the
offline fallback.

If you add restaurants to `index.html` but not to
`supabase/restaurants-import.csv`, here's exactly what happens: the new
category or restaurants render fine on your local test (which uses the
embedded array), you deploy to QAS, and the category chip is silently
**disabled** — greyed out, "此條件下無結果" — because the live Supabase data
has zero matches for it. It looks like a filtering bug. It isn't; it's a data
sync gap. (This happened for real: a "健康餐" category worked locally and on
DEV's static check, but was unselectable on QAS until the CSV was fixed.)

So: every restaurant you add to `embeddedRestaurants` also needs a row
appended to `supabase/restaurants-import.csv`, in the exact column order
`name,area,lat,lng,categories,price,rating,description,tags,phone,parking_tier,parking_sub,photos,maps_url,hours`.
Array-typed columns (`categories`, `tags`, `photos`) use Postgres array literal
syntax: `{"item1","item2"}`. The `hours` column is a **JSON array** (the same
7-day structure as the JS `HOURS` value, e.g.
`[[],[[1050,1440]],...]`) written as compact JSON text, not a JS-quoted string.
Use `scripts/build_csv_rows.py` to generate correctly-escaped rows from the
same details JSON you already fetched in step 4 — don't hand-write CSV rows,
the quoting rules for embedded commas/quotes in restaurant names and
descriptions are easy to get subtly wrong.

Append with a plain Python read-write (preserve the file's existing `\n` line
endings; don't leave a stray blank line at the join point), then sanity-check
by parsing the whole file with the *actual* parser
(`scripts/import-restaurants.mjs`'s `parseCsv`, or copy its logic into a quick
Node check) to confirm column counts match on every row before committing.

## 8. If this is a new category: update `CAT_GROUPS`

Add the new label to `CAT_GROUPS` in `index.html`, mapping to the detailed cat
string(s) you used in step 5. Ask the user (or infer from context) where in
the chip order it should go — this project cares about chip ordering as a
deliberate UX decision, it's not just "append to the end." If they don't say,
a reasonable default is near thematically similar existing chips.

Also add an entry to `CAT_VISUAL` (search for `const CAT_VISUAL` — it's the
`{ch: "single-character-icon", bg: "#hexcolor"}` map used for the SVG
placeholder shown before a photo loads) so new-category cards don't fall back
to the generic "食" icon. Pick a background color visually distinct from
existing entries.

## 9. Validate before deploying — every time, no exceptions

```bash
python3 -c "
import re
html = open('index.html', encoding='utf-8').read()
m = re.search(r'<script>(.*)</script>', html, re.S)
open('/tmp/extracted.js','w',encoding='utf-8').write(m.group(1))
"
node --check /tmp/extracted.js && echo SYNTAX_OK
```

Then Playwright checks — reuse `scripts/test_new_restaurants.js` as a template
(pass it the new category label and expected count, or the list of new
restaurant names to look for), and separately run the project's existing full
regression script if one exists in scratchpad from a prior session (checks
total card count, photo-carousel image/dot counts match, favorites still work,
category filter still works, zero console errors). At minimum verify:

- Total card count increased by exactly the number of restaurants you added
- The new/updated category chip is selectable and filters to the right count
- If you added a brand-new category, it appears in the chip list in the
  position you intended
- No new JS console errors

This sandbox generally cannot reach `supabase.co`, `*.pages.dev`, or
`*.github.io` (network egress is restricted) — don't try to verify the live
Supabase sync or deployed sites directly from here. Verify locally with the
static file, trust the GitHub Actions run result for the Supabase side (step
10), and ask the user to eyeball the deployed QAS site.

## 10. Deploy: DEV → QAS (auto-syncs Supabase) → wait for user → PRD

```bash
git add index.html supabase/restaurants-import.csv
git commit -m "<describe what was added and why>"
git push -u origin DEV
```

Once validated, fast-forward the same commit to QAS:

```bash
git checkout QAS
git pull origin QAS
git merge DEV --ff-only
git push -u origin QAS
git checkout DEV
```

Pushing to `QAS` triggers `.github/workflows/sync-supabase-restaurants.yml`
automatically (it fires on *any* push to `QAS`, not just CSV changes — this
was a deliberate choice so this skill's workflow doesn't need to remember a
path filter). That workflow runs `scripts/import-restaurants.mjs`, which
upserts every CSV row into Supabase keyed on `on_conflict=name`. Confirm it
succeeded:

```
mcp__github__actions_list(method: "list_workflow_runs", ..., resource_id: "sync-supabase-restaurants.yml", per_page: 1)
```

Look for `"conclusion":"success"` on the run matching your latest commit sha.
If it fails, read the job logs (`mcp__github__get_job_logs`) before assuming
anything — the two failure modes seen so far were (a) `409 duplicate key`
because `on_conflict=name` was missing from the upsert URL, and (b) the
workflow's `on.push.branches` filter pointing at a stale/renamed branch name
that no longer matches the actual branch — check
`.github/workflows/sync-supabase-restaurants.yml`'s branch list matches the
real branch names in the repo before assuming the script itself is broken.

**Do not merge to `PRD` yourself.** Tell the user QAS is ready and ask them to
confirm it looks right on the live QAS site before you (or they) promote to
PRD. When they confirm, the promotion is the same fast-forward pattern:
`git checkout PRD && git pull && git merge QAS --ff-only && git push`.

## 11. Clean up

Delete the API key file if you haven't already (`rm -f`). Leave scratch data
files (candidate JSON, details JSON, CSV/JS append fragments) in the
scratchpad — they're useful if the user asks for a correction to this batch
later, and the scratchpad isn't part of the repo anyway.

## Reporting back to the user

Summarize in Traditional Chinese: what was added (names, areas, category),
what got validated, and the current deployment state (DEV done, QAS done and
Supabase-synced, waiting on their confirmation before PRD). Don't claim PRD is
live unless you actually merged it.
