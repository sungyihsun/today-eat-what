# 今天吃什麼

新竹市 / 竹北 / 桃園（中壢・青埔）餐廳地圖，依分類、地區、營業時間篩選。

## 部署環境

| 分支  | 用途           | pages.dev                         | 自訂網域                    |
|-------|----------------|------------------------------------|------------------------------|
| `DEV` | 開發中，未驗證 | dev-what-to-eat-today.pages.dev   | dev.eat.easonsung.com       |
| `QAS` | 驗證中，待確認 | qas-what-to-eat-today.pages.dev   | qas.eat.easonsung.com       |
| `PRD` | 正式站         | what-to-eat-today-7g0.pages.dev   | eat.easonsung.com           |

`DEV` / `QAS` 部署在 Cloudflare Pages；`PRD` 同時也接 GitHub Pages
（`sungyihsun.github.io/today-eat-what/`）。

## 開發流程

1. 新功能／資料更新先開發並驗證在 `DEV`
2. 確認沒有錯誤（語法檢查、功能測試）後推到 `QAS`，供人工確認實際使用沒問題
3. `QAS` 確認沒問題後推到 `PRD`
4. 推上 `PRD` 後，三個分支內容對齊（`DEV` = `QAS` = `PRD`）

## Supabase 整合

`QAS` / `PRD` 前端會優先讀取 Supabase 的 `restaurants` 表，讀取失敗時
fallback 用內嵌在 `index.html` 裡的離線資料。細節見
[`supabase/README.md`](supabase/README.md)。

新增或修改餐廳資料時，`supabase/restaurants-import.csv` 跟著更新並 push
到 `QAS` 分支，GitHub Actions（`.github/workflows/sync-supabase-restaurants.yml`）
會自動把資料同步進 Supabase。
