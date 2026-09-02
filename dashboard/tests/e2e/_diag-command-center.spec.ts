import { test } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

// Diagnostic: load /command-center, capture console errors + page state.
// Reads dashboard creds from .env.local itself (never printed).
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

test("diagnose command-center crash", async ({ browser }) => {
  const { user, pass } = loadCreds();
  const context = await browser.newContext({ httpCredentials: { username: user, password: pass } });
  const page = await context.newPage();

  const logs: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") logs.push(`[console.error] ${msg.text()}`);
  });
  page.on("pageerror", (err) => logs.push(`[pageerror] ${err.message}\n${err.stack || ""}`));

  await page.goto("/command-center", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(6000);

  const bodyText = await page.evaluate(() => document.body.innerText.slice(0, 600));
  console.log("=== BODY TEXT (first 600) ===");
  console.log(bodyText);
  console.log("=== ERRORS ===");
  console.log(logs.join("\n---\n") || "(none)");
  await context.close();
});
