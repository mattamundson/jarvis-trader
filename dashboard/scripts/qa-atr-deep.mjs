import { chromium } from '../node_modules/.pnpm/playwright@1.61.1/node_modules/playwright/index.mjs';

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await context.newPage();
const consoleMsgs = [];
const pageErrors = [];
const apiCalls = [];
page.on('console', (msg) => { if (msg.type() === 'error') consoleMsgs.push(msg.text()); });
page.on('pageerror', (err) => pageErrors.push(err.message));
page.on('response', (res) => { if (res.url().includes('/api/')) apiCalls.push(`${res.status()} ${res.url()}`); });

await page.goto('http://127.0.0.1:3010/atr-trail', { waitUntil: 'domcontentloaded', timeout: 30000 });
await page.waitForTimeout(25000);
try { await page.waitForLoadState('networkidle', { timeout: 15000 }); } catch {}

const bodyText = await page.evaluate(() => document.body.innerText);
await page.screenshot({ path: 'C:\\Users\\mattm\\.claude\\analysis\\dashboard-qa\\screenshots\\atr-trail-deep.png', fullPage: true });
console.log('apiCalls:', JSON.stringify(apiCalls, null, 2));
console.log('consoleErrors:', JSON.stringify(consoleMsgs, null, 2));
console.log('pageErrors:', JSON.stringify(pageErrors, null, 2));
console.log('bodyText snippet:', bodyText.slice(0, 1500));
await browser.close();
