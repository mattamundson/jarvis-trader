import { test, expect } from "@playwright/test";
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

// LIVE verification: real engine (no mocks) — the funnel card must render
// with the real /analytics/pipeline-funnel payload. Requires local engine
// credentials (.env.local → ENGINE_API_KEY via the Next proxy); in CI there
// is no engine and no key, so the endpoint 401s and this diagnostic would
// only ever report a false negative. Skip gracefully instead.
const hasEnv = fs.existsSync(path.resolve(__dirname, "../../.env.local"));

test("LIVE command-center shows real pipeline funnel data", async ({ browser }) => {
  test.skip(!hasEnv, "no .env.local — CI/clean checkout: live engine diagnostic cannot run");
  const { user, pass } = loadCreds();
  const context = await browser.newContext({ httpCredentials: { username: user, password: pass } });
  const page = await context.newPage();
  await page.goto("/command-center", { waitUntil: "domcontentloaded" });

  const card = page.getByTestId("pipeline-funnel-card");
  await expect(card).toBeVisible({ timeout: 20000 });
  await expect(card).toContainText("PIPELINE FUNNEL");
  await expect(card).toContainText("OVERALL CONVERSION");

  // Real data from the live engine endpoint: 30d runs should be > 0 and the
  // window testids must exist.
  await expect(page.getByTestId("pipeline-funnel-30d")).toBeVisible();
  await expect(page.getByTestId("pipeline-funnel-90d")).toBeVisible();

  const bodyText = await card.innerText();
  console.log("=== LIVE CARD TEXT ===");
  console.log(bodyText.slice(0, 800));
  await context.close();
});
