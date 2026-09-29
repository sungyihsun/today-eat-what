// Usage (repo root): NODE_PATH=/opt/node22/lib/node_modules node .claude/skills/add-restaurant/scripts/verify_area.js <area> <expectedAreaCount> <expectedTotal>
// Loads index.html, checks the total card count, filters to the area, and reports JS errors. Exit 1 on any mismatch.
const { chromium } = require('playwright');
const path = require('path');
const [area, wantArea, wantTotal] = [process.argv[2], Number(process.argv[3]), Number(process.argv[4])];
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto('file://' + path.resolve('index.html'), { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  const total = await page.$eval('#resultCount', el => el.textContent);
  const areaText = await page.evaluate(a => { state.area = a; render(); return document.querySelector('#resultCount').textContent; }, area);
  const num = s => Number((s.match(/\d+/) || [])[0]);
  console.log(`total: ${total} (expect ${wantTotal}) | area=${area}: ${areaText} (expect ${wantArea}) | JS errors: ${errors.length ? JSON.stringify(errors) : 'none'}`);
  await browser.close();
  process.exit(num(total) === wantTotal && num(areaText) === wantArea && !errors.length ? 0 : 1);
})();
