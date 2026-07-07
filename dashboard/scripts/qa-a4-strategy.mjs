// One-off QA script for A4-strategy dashboard audit. Read-only: navigates pages,
// captures console errors, network failures, and screenshots. Does NOT click
// mutating buttons (run-backtest is inspected but only clicked if clearly a
// read-only compute persisted to DB per task instructions -- here we default
// to NOT clicking to stay strictly read-only; noted in report).
import { chromium } from '../node_modules/.pnpm/playwright@1.61.1/node_modules/playwright/index.mjs';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:3010';
const OUT_DIR = 'C:\\Users\\mattm\\.claude\\analysis\\dashboard-qa\\screenshots';
fs.mkdirSync(OUT_DIR, { recursive: true });

const pages = [
  { path: '/strategies', name: 'strategies' },
  { path: '/strategy-c', name: 'strategy-c' },
  { path: '/strategy-c-command', name: 'strategy-c-command' },
  { path: '/strategy-ledger', name: 'strategy-ledger' },
  { path: '/strategy-research', name: 'strategy-research' },
  { path: '/backtest', name: 'backtest' },
  { path: '/atr-trail', name: 'atr-trail' },
  { path: '/stats', name: 'stats' },
];

const results = [];

const browser = await chromium.launch({ headless: true });

for (const p of pages) {
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();

  const consoleMsgs = [];
  const pageErrors = [];
  const failedRequests = [];
  const apiCalls = [];

  page.on('console', (msg) => {
    if (msg.type() === 'error' || msg.type() === 'warning') {
      consoleMsgs.push(`[${msg.type()}] ${msg.text()}`);
    }
  });
  page.on('pageerror', (err) => {
    pageErrors.push(err.message);
  });
  page.on('requestfailed', (req) => {
    failedRequests.push(`${req.method()} ${req.url()} :: ${req.failure()?.errorText}`);
  });
  page.on('response', (res) => {
    const url = res.url();
    if (url.includes('/api/') || url.includes(':8010')) {
      apiCalls.push(`${res.status()} ${url}`);
    }
  });

  const rec = { name: p.name, path: p.path, loads: false, httpStatus: null, consoleMsgs, pageErrors, failedRequests, apiCalls, bodyTextSnippet: '', screenshot: null, errorBoundary: false, title: '' };

  try {
    const resp = await page.goto(BASE + p.path, { waitUntil: 'domcontentloaded', timeout: 30000 });
    rec.httpStatus = resp ? resp.status() : null;
    rec.loads = !!resp && resp.status() < 400;
    // Give client-side data fetching (SWR) time to settle
    await page.waitForTimeout(4000);
    try {
      await page.waitForLoadState('networkidle', { timeout: 8000 });
    } catch {}
    rec.title = await page.title();
    const bodyText = await page.evaluate(() => document.body.innerText).catch(() => '');
    rec.bodyTextSnippet = bodyText.slice(0, 3000);
    // Detect Next.js error boundary / React error overlay signatures
    const html = await page.content();
    rec.errorBoundary = /Application error/i.test(bodyText) || /a client-side exception/i.test(bodyText) || /__next-dev-overlay/i.test(html) || /Something went wrong/i.test(bodyText);
    const shotPath = path.join(OUT_DIR, `${p.name}.png`);
    await page.screenshot({ path: shotPath, fullPage: true });
    rec.screenshot = shotPath;
  } catch (e) {
    rec.error = String(e);
    try {
      const shotPath = path.join(OUT_DIR, `${p.name}-FAILED.png`);
      await page.screenshot({ path: shotPath, fullPage: true }).catch(() => {});
      rec.screenshot = shotPath;
    } catch {}
  }

  results.push(rec);
  await context.close();
}

await browser.close();

fs.writeFileSync(
  'C:\\Users\\mattm\\.claude\\analysis\\dashboard-qa\\a4-strategy-raw.json',
  JSON.stringify(results, null, 2)
);

console.log('DONE. Pages processed:', results.length);
for (const r of results) {
  console.log(`\n=== ${r.name} (${r.path}) ===`);
  console.log('HTTP:', r.httpStatus, 'loads:', r.loads, 'title:', r.title);
  console.log('errorBoundary:', r.errorBoundary);
  console.log('console msgs:', r.consoleMsgs.length, 'pageErrors:', r.pageErrors.length, 'failedReqs:', r.failedRequests.length);
}
