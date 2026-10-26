import { chromium } from "@playwright/test";
import { readFileSync } from "node:fs";

const envText = readFileSync(new URL("./.env.local", import.meta.url), "utf8");
const env = {};
for (const line of envText.split(/\r?\n/)) {
  if (!line || line.trim().startsWith("#") || !line.includes("=")) continue;
  const idx = line.indexOf("=");
  env[line.slice(0, idx).trim()] = line.slice(idx + 1).trim().replace(/^['"]|['"]$/g, "");
}
if (!env.DASHBOARD_AUTH_USER || !env.DASHBOARD_AUTH_PASS) {
  throw new Error("Dashboard basic auth is not set");
}

const browser = await chromium.launch({ channel: "chrome", headless: true });
const context = await browser.newContext({
  httpCredentials: {
    username: env.DASHBOARD_AUTH_USER,
    password: env.DASHBOARD_AUTH_PASS,
  },
  viewport: { width: 1440, height: 900 },
});
const page = await context.newPage();
const resp = await page.goto("http://127.0.0.1:3010/mission-control", {
  waitUntil: "domcontentloaded",
  timeout: 30000,
});
await page.waitForTimeout(8000);
const body = (await page.locator("body").innerText()).replace(/\s+/g, " ");
const at = body.indexOf("Drawdown Projection");
const slice = at >= 0 ? body.slice(at, at + 280) : "PROJECTION_MISSING";
console.log("PAGE_STATUS=" + (resp ? resp.status() : "none"));
console.log("PROJECTION=" + slice);
console.log("HAS_6_48=" + slice.includes("6.48"));
console.log("HAS_12_08=" + body.includes("12.08"));
await browser.close();
