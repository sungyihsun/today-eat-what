# 台中全區補完（排程 runbook）

排程每次觸發，**只做一個行政區**，做完就結束。你是全新的 session，沒有先前對話的記憶——
這份文件加上 `SKILL.md` 就是全部的背景。先讀 `SKILL.md`（尤其是 Supabase CSV 那一節），再照這份做。

## 0. 開工前檢查（任何一項不符就停下來，不要硬做）

```bash
cd <repo root>            # 本機通常是 /home/user/VLM_SOP；沒有的話用 add_repo 掛 sungyihsun/today-eat-what
git checkout DEV && git pull --rebase origin DEV
git status --short        # 必須乾淨
cat candidate-results/taichung-progress.json
```

- `in_progress` 不為 null 且 `started_at` 距今 < 3 小時 → 上一輪還在跑，**直接結束**（回報「上一輪進行中」）。
- `in_progress` 不為 null 且超過 3 小時 → 上一輪中斷了。檢查它做到哪（`picks.json`、`details.json`、CSV 是否已有該區資料、
  DEV/QAS 是否已推），從斷點接續，不要重來，也不要重複加同一區。
- `queue` 是空的 → 全部做完了，見 §6。

## 1. 選區並記錄

取 `queue` 的第一個。把它寫進 `taichung-progress.json` 的 `in_progress`
（`{"district": ..., "started_at": "<UTC ISO>"}`），commit + push DEV，讓重疊的排程看得到。

`queue` 每項欄位：`area`（存進每筆餐廳 `area` 欄位的值）、`label`（chip 文字與搜尋標籤）、`slug`（檔名用 ascii）、
`center`（[lat,lng]，locationBias 中心）、`landmarks`（額外搜尋關鍵字）。
`東/北/中/南區` 這類只有方位的區名，`area` 與 `label` 都加「台中」前綴（`台中東區`），因為新竹市等別的城市也有同名區。

## 2. 搜尋（只搜尋，不挑選）

編輯 `.claude/skills/add-restaurant/scripts/search_candidates.py`：把 `AREAS`、`QUERIES` **整個換成**這個區
（`AREAS = {label: center}`；`QUERIES = {label: [...]}`）。查詢用「<區名> 餐廳 / 早午餐 / 日式料理 / 義式料理 / 燒烤 / 火鍋 /
甜點 / 咖啡廳 / 韓式料理 / 熱炒 / 小吃」加上 `landmarks`，約 12 條。地址比對 `AREA_KEYWORDS` **不用改**——
`area_keywords()` 會依 `TC_DISTRICTS` 自動產生（含「臺／台」四種寫法）；label 必須是 `TC_DISTRICTS` 裡的名字。

push DEV 會觸發 `search-restaurant-candidates.yml`，它把結果發布成 `candidate-results/latest.json`。
等它成功（背景 `sleep` 等，不要輪詢）後 `git pull --rebase origin DEV`。

**馬上凍結**：`cp candidate-results/latest.json candidate-results/search-<slug>.json`。之後任何 push 都可能重跑搜尋、
覆蓋 `latest.json`，而 Text Search 每次回傳的集合都略有不同（曾因此漏掉 30 家裡的 6 家）。**一律用凍結檔挑店。**

## 3. 挑店（判斷力在這裡）

從凍結檔挑**最多 30 家**，依評分＋評論數排序後，刻意分散類型（燒肉、火鍋、日式、居酒屋、義式、韓式、泰式、台式/小吃、
港式、早午餐、熱炒、甜點、咖啡…），同一類別最多約 5 家，避免全是火鍋或燒肉。原則：

- 只挑真的餐廳/咖啡廳/甜點店。排除：花店、超市/零食店、夜市整體 listing、共享空間、DIY 工作室、旅館、加油站、
  診所；名稱帶「夏季店休N個月」這類長期停業字樣的；評論數過少（<25）除非該類型在此區很稀有。
- 偏鄉區（山區/海線）合格店家少：有多少真的好店就挑多少。**少於 8 家就不要硬湊**，把這區記到 `skipped`（附原因）並結束。
- 連鎖不同分店是不同店（cid 不同），可以收；但同一批不要同品牌超過 2 家。
- 名稱必須與凍結檔中的 `name` **完全一致**（含全形符號、`專` vs `専` 這類字形）；用程式比對取出，不要手打。
- 與既有資料撞名/撞 cid 會被 `build_district.py` 擋下，先自己比對過：
  `re.findall(r'\{name:"((?:[^"\\]|\\.)*)"', html)` 與 `cid=(\d+)`。

寫 `candidate-results/picks.json`：
```json
{"area": "<area>", "candidates_file": "candidate-results/search-<slug>.json", "picks": ["<exact name>", ...]}
```
（`area` 這裡填**搜尋標籤**，也就是 label，要和凍結檔裡 `area_label` 一致。）
commit（連同凍結檔）+ push DEV → 觸發 `fetch-restaurant-details.yml`。它**不重新搜尋**，直接對凍結檔解析、抓 Place Details，
並在「抓到的家數 ≠ 挑選家數」時讓 workflow 失敗。失敗就看 log 的 `missing:` 行修正 picks 後重推；
成功後它會發布 `candidate-results/details.json`。等它成功後 `git pull --rebase origin DEV`。

## 4. 建資料、驗證、部署

寫 `candidate-results/config-<slug>.json`（要 commit，當作紀錄）：
```json
{"area": "<area>", "label": "<label>", "region": "中部",
 "cats":  {"<raw google name>": ["<CAT_GROUPS_FOOD 裡已存在的細分類字串>", ...]},
 "names": {"<raw google name>": "<去掉行銷字尾的乾淨店名>"},
 "tags":  {"<raw google name>": ["標籤", "標籤", "高評價"]}}
```
- `cats` 每家都要有；字串必須已存在於 `index.html` 的 `CAT_GROUPS_FOOD`（如 `燒烤`、`火鍋/鍋物`、`日式料理`、`居酒屋`、
  `義式料理`、`韓式料理`、`泰式料理`、`台式/客家合菜`、`港式料理`、`早午餐`、`早餐店`、`熱炒`、`甜點/烘焙`、`咖啡廳`、`牛排`、
  `麵食/小吃`、`吃到飽`…），不認識的會被腳本擋下。**不要新增分類**。
- `names`：Google 名稱常帶「｜…」「| …」「（最後收客…）」「#標籤」之類行銷字尾，去掉。分店名保留。
- 跑（repo 根目錄）：
  ```bash
  python3 .claude/skills/add-restaurant/scripts/build_district.py candidate-results/config-<slug>.json
  ```
  它同時寫 `index.html`（`HOURS` + `embeddedRestaurants`）與 `supabase/restaurants-import.csv`，並自動開啟或新增該區的 chip。
  它遇到撞名/撞 cid/未知分類/CSV 格式錯誤會直接退出且**不寫任何檔案**。
- 驗證（缺一不可）：
  ```bash
  python3 -c "import re;h=open('index.html',encoding='utf-8').read();open('/tmp/x.js','w',encoding='utf-8').write(re.search(r'<script>(.*)</script>',h,re.S).group(1))" && node --check /tmp/x.js
  NODE_PATH=/opt/node22/lib/node_modules node .claude/skills/add-restaurant/scripts/verify_area.js "<area>" <本區家數> <原總數+本區家數>
  ```
  原總數＝動手前 `restaurants-import.csv` 的資料列數（不含表頭）。verify 沒過就修，不要推。
- commit（繁體中文說明；遵循該次 session 給的署名規則）→ push DEV（被拒就 `git pull --rebase origin DEV` 再推）。
- 推 QAS（fast-forward）：
  ```bash
  git fetch origin QAS && git checkout -B QAS origin/QAS && git merge origin/DEV --ff-only && git push origin QAS && git checkout DEV
  ```
  推 QAS 會觸發 `sync-supabase-restaurants.yml`。用 GitHub MCP（owner `sungyihsun`、repo `today-eat-what`）確認該 workflow
  對應 commit 的 run `conclusion: success`。失敗就讀 job log 處理；處理不了就在 progress 記 `failed` 與原因後結束。
- **絕對不要推 PRD。** 排程只到 QAS；PRD 由使用者看過後說「上PRD」再一次推上去。

## 5. 收尾

更新 `candidate-results/taichung-progress.json`：把該區從 `queue` 移到 `done`
（`{"area", "count", "qas_commit", "finished_at"}`），`in_progress` 設回 `null`；commit + push DEV，再把 DEV fast-forward 到 QAS
（讓 QAS 也有最新 progress 檔；這個檔在 `candidate-results/`，不影響網站）。然後結束，回報一句話：這區加了幾家、QAS 已同步。

## 6. 全部做完時

`queue` 為空：回報「台中全區完成，QAS 待使用者上 PRD」。並停用排程：用 `mcp__Claude_Code_Remote__list_triggers` 找名稱為
「台中餐廳補完」的 routine，`update_trigger` 設 `enabled:false`（找不到或沒有權限就只回報）。

## 已知地雷（都真的踩過）

- 地址是「臺中市」不是「台中市」——`area_keywords()` 已處理，別自己寫 `"台中市"` 比對。
- 搜尋結果不穩定 → 一律用凍結檔；不要在 fetch 前重新搜尋。
- `embeddedRestaurants` 只是 DEV/離線 fallback，QAS/PRD 讀 Supabase ← CSV。`build_district.py` 兩邊都寫；不要手動只改一邊。
- `git push` 被拒（fetch first）是因為 bot 會自己推 `candidate-results/*`：`git pull --rebase origin DEV` 再推。
- `mcp__github__actions_run_trigger` 的 `run_workflow` 會 403，靠 push 觸發 workflow，不要試 dispatch。
- 本機沙盒連不上 `lh3.googleusercontent.com`／Google API，所有 Google 呼叫都在 GitHub Actions 上跑。
