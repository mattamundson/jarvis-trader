import { test } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

function loadCreds() {
  const p = path.resolve(__dirname, "../../.env.local");
  let user = "", pass = "";
  // CI has no .env.local (auth is off there); skip gracefully instead of
  // failing the diagnostic.
  if (fs.existsSync(p)) {
    for (const line of fs.readFileSync(p, "utf8").split("\n")) {
      const m = line.match(/^DASHBOARD_AUTH_USER=(.*)$/);
      if (m) user = m[1].trim();
      const m2 = line.match(/^DASHBOARD_AUTH_PASS=(.*)$/);
      if (m2) pass = m2[1].trim();
    }
  }
  return { user, pass };
}

test("diagnose funnel mock crash: log engine requests", async ({ browser }) => {
  const { user, pass } = loadCreds();
  const context = await browser.newContext({ httpCredentials: { username: user, password: pass } });
  const page = await context.newPage();

  const requests: string[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/api/engine/")) requests.push(req.url().replace(/^.*\/api\/engine/, "/api/engine"));
  });
  page.on("console", (msg) => {
    if (msg.type() === "error") console.log(`[console.error] ${msg.text().slice(0, 300)}`);
  });
  page.on("pageerror", (err) => console.log(`[pageerror] ${err.message?.slice(0, 300)}\n${(err.stack || "").split("\n").slice(0, 4).join("\n")}`));

  // Generic mock like the funnel spec uses
  await page.route("**/api/engine/**", (route) => {
    const u = route.request().url();
    if (u.includes("/prices/snapshot")) {
      return route.fulfill({
        json: {
          MES: { last_price: null, prev_close: null, change_pct: null, error: "No data available" },
          MGC: { last_price: null, prev_close: null, change_pct: null, error: "No data available" },
        },
      });
    }
    return route.fulfill({ status: 200, json: {} });
  });

  await page.goto("/command-center", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(8000);

  console.log("=== ENGINE REQUESTS ===");
  console.log(requests.join("\n"));
  console.log("=== PAGE STATE ===");
  const bodyText = await page.evaluate(() => document.body.innerText.slice(0, 400));
  console.log(bodyText);
  await context.close();
});
