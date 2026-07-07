import { chromium } from '../node_modules/.pnpm/playwright@1.61.1/node_modules/playwright/index.mjs';

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await context.newPage();

const consoleMsgs = [];
const pageErrors = [];
page.on('console', (msg) => {
  if (msg.type() === 'error' || msg.type() === 'warning') consoleMsgs.push(`[${msg.type()}] ${msg.text()}`);
});
page.on('pageerror', (err) => pageErrors.push(err.message));

await page.goto('http://127.0.0.1:3010/stats', { waitUntil: 'domcontentloaded', timeout: 30000 });
// Give it a generous 20s for all ~24 widgets to settle
await page.waitForTimeout(20000);
try { await page.waitForLoadState('networkidle', { timeout: 15000 }); } catch (e) { console.log('networkidle wait failed:', e.message); }

const bodyText = await page.evaluate(() => document.body.innerText);
await page.screenshot({ path: 'C:\\Users\\mattm\\.claude\\analysis\\dashboard-qa\\screenshots\\stats-deep.png', fullPage: true });

console.log('=== consoleMsgs ===');
console.log(JSON.stringify(consoleMsgs, null, 2));
console.log('=== pageErrors ===');
console.log(JSON.stringify(pageErrors, null, 2));
console.log('=== bodyText (first 4000) ===');
console.log(bodyText.slice(0, 4000));

await browser.close();
