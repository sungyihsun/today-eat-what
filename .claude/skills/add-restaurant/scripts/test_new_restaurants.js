/**
 * Template: validate a batch of newly-added restaurants against index.html.
 *
 * EDIT PER TASK:
 *   - INDEX_HTML_PATH if running from a different cwd
 *   - EXPECTED_TOTAL: previous total card count + number of restaurants added
 *   - CATEGORY_LABEL: the chip label to test-filter by (existing or newly added)
 *   - EXPECTED_CATEGORY_COUNT: how many cards should show when filtered to it
 *
 * Run with: NODE_PATH=/opt/node22/lib/node_modules node test_new_restaurants.js
 * (adjust NODE_PATH to wherever this environment's playwright package lives)
 */
const { chromium } = require('playwright');
const path = require('path');

const INDEX_HTML_PATH = path.resolve('index.html'); // EDIT if needed
const EXPECTED_TOTAL = null; // EDIT: e.g. 420
const CATEGORY_LABEL = null; // EDIT: e.g. '健康餐'
const EXPECTED_CATEGORY_COUNT = null; // EDIT: e.g. 14

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));

  await page.goto('file://' + INDEX_HTML_PATH, { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);

  const totalCards = await page.$$eval('.card', els => els.length);
  console.log('total cards:', totalCards, EXPECTED_TOTAL !== null ? `(expect ${EXPECTED_TOTAL})` : '');
  if (EXPECTED_TOTAL !== null && totalCards !== EXPECTED_TOTAL) {
    console.log('  !! MISMATCH — investigate before deploying');
  }

  if (CATEGORY_LABEL) {
    // Expand the multi-select category chip picker (id="catToggle"), following
    // the same interaction pattern as the live UI: click the collapsed
    // summary pill once, then click the target chip by its exact text.
    await page.click('#catToggle button.active');
    await page.waitForTimeout(200);
    const chipLabels = await page.$$eval('#catToggle button', btns => btns.map(b => b.textContent.trim()));
    console.log('chip labels:', JSON.stringify(chipLabels));
    if (!chipLabels.includes(CATEGORY_LABEL)) {
      console.log(`  !! "${CATEGORY_LABEL}" is not in the chip list at all — check CAT_GROUPS`);
    }

    const btns = await page.$$('#catToggle button');
    let clicked = false;
    for (const b of btns) {
      const t = (await b.textContent()).trim();
      if (t === CATEGORY_LABEL || t === '✓ ' + CATEGORY_LABEL) {
        const disabled = await b.evaluate(el => el.disabled);
        if (disabled) {
          console.log(`  !! chip "${CATEGORY_LABEL}" is DISABLED — this is exactly the symptom of the`);
          console.log('     "forgot to update supabase/restaurants-import.csv" bug when testing against');
          console.log('     a build that reads from Supabase. If you\'re testing the static file directly');
          console.log('     it should never be disabled — investigate index.html\'s CAT_GROUPS/data instead.');
        }
        await b.click();
        clicked = true;
        break;
      }
    }
    if (!clicked) console.log(`  !! could not find/click chip "${CATEGORY_LABEL}"`);
    await page.waitForTimeout(300);

    const filteredCount = await page.$$eval('.card', els => els.length);
    const names = await page.$$eval('.card-name', els => els.map(e => e.textContent.trim()));
    console.log(`${CATEGORY_LABEL} filter count:`, filteredCount,
      EXPECTED_CATEGORY_COUNT !== null ? `(expect ${EXPECTED_CATEGORY_COUNT})` : '');
    console.log('names:', JSON.stringify(names));
    if (EXPECTED_CATEGORY_COUNT !== null && filteredCount !== EXPECTED_CATEGORY_COUNT) {
      console.log('  !! MISMATCH — investigate before deploying');
    }
  }

  console.log('JS ERRORS:', errors.length ? JSON.stringify(errors) : 'none');
  await browser.close();
})();
