import { test, expect } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

/**
 * ActionableBoardWidget (T8): real entry/stop/T1/T2 cards + honest empty state.
 *
 * The widget fetches /pipeline/actionable through the engine proxy. We mock
 * that proxy with three response shapes:
 *  1. a populated board → cards render entry/stop/T1/T2/last + status chip;
 *  2. raw_count > 0, shown == 0 → "queue has N rows but none qualify" copy
 *     (queue state, NOT a market claim);
 *  3. raw_count == 0 with last_pipeline_run_at → "no recent decisions / pipeline
 *     last ran" copy (engine ran but offered nothing);
 *  4. raw_count == 0 with last_pipeline_run_at == null → "pipeline is not
 *     running" copy (engine-offline diagnosis, not "no opportunities").
 *
 * Run with the FRESH config (pnpm run test:e2e:fresh) so it exercises the
 * current build on a port pm2 does not own — never the reused production
 * dashboard on :3010.
 */

const ACTIONABLE_URL = "**/api/engine/pipeline/actionable*";

// The dashboard sits behind Basic Auth ONLY when DASHBOARD_AUTH_USER/PASS are
// set (middleware.ts logs "UNAUTHENTICATED" and skips the challenge otherwise).
// CI runs without .env.local (auth off), so this must not hard-crash when the
// file is missing — missing file => empty creds => httpCredentials unused.
function loadCreds() {
  const p = path.resolve(__dirname, "../../.env.local");
  let user = "",
    pass = "";
  try {
    const text = fs.readFileSync(p, "utf8");
    for (const line of text.split("\n")) {
      const m = line.match(/^DASHBOARD_AUTH_USER=(.*)$/);
      if (m) user = m[1].trim();
      const m2 = line.match(/^DASHBOARD_AUTH_PASS=(.*)$/);
      if (m2) pass = m2[1].trim();
    }
  } catch {
    // .env.local absent (CI / fresh checkout) — auth is off, pages render
    // anonymously. Same fallback contract the dashboard itself uses.
  }
  return { user, pass };
}

const { user, pass } = loadCreds();
test.use({ httpCredentials: { username: user, password: pass } });

const FIXTURE_ITEM = {
  approval_id: "queue-888",
  symbol: "MES",
  direction: "long",
  action: "buy",
  approval_status: "approved",
  quantity: 2,
  confidence: 0.55,
  timeframe: "1h",
  created_at: "2026-08-18T13:49:40+00:00",
  age_days: 0,
  status: "awaiting_entry",
  entry_price: 7724.25,
  stop_loss: 7715.44,
  target_1: 7746.28,
  target_2: 7759.5,
  atr: 8.81,
  latest_price: 7683.0,
  price_as_of: 1752600000,
  price_is_live: false,
  price_stale: false,
  distance_abs: 41.25,
  distance_pct: 0.5368,
  distance_atr: 4.68,
  planned_rr: 1.5,
  current_r: -4.64,
  notional_per_contract: 38415.0,
};

async function mockActionable(page: import("@playwright/test").Page, payload: unknown) {
  // Catch-all FIRST (Playwright matches routes in reverse registration order,
  // so the specific actionable route registered after wins for its URLs).
  await page.route("**/api/engine/**", (route) => route.fulfill({ status: 200, json: {} }));
  await page.route(ACTIONABLE_URL, (route) => route.fulfill({ status: 200, json: payload }));
}

test("actionable board renders real entry/stop/T1/T2 cards from queue data", async ({ page }) => {
  await mockActionable(page, {
    items: [FIXTURE_ITEM],
    count: 1,
    available: true,
    raw_count: 1,
    shown: 1,
    source: "queue",
    last_pipeline_run_at: "2026-08-25T18:47:46",
  });

  await page.goto("/paper", { waitUntil: "domcontentloaded" });

  const cards = page.getByTestId("actionable-item");
  await expect(cards).toHaveCount(1);

  const card = cards.first();
  await expect(card).toContainText("MES");
  await expect(card).toContainText("long");
  await expect(card).toContainText("awaiting entry");
  // The geometry the T8 card must surface:
  await expect(card).toContainText("7724.25"); // entry
  await expect(card).toContainText("7715.44"); // stop
  await expect(card).toContainText("7746.28"); // T1
  await expect(card).toContainText("7759.50"); // T2
  await expect(card).toContainText("7683.00"); // last
  await expect(card).toContainText("planned RR");
  await expect(card).toContainText("current R");
});

test("empty state with filtered queue explains queue state, not market claim", async ({ page }) => {
  await mockActionable(page, {
    items: [],
    count: 0,
    available: true,
    raw_count: 12,
    shown: 0,
    source: "queue",
    last_pipeline_run_at: "2026-08-25T18:47:46",
  });

  await page.goto("/paper", { waitUntil: "domcontentloaded" });

  const empty = page.getByTestId("actionable-empty");
  await expect(empty).toBeVisible();
  await expect(empty).toContainText("12 recent rows");
  await expect(empty).toContainText("none qualify as actionable");
  await expect(empty).toContainText("queue state, not a claim");
});

test("empty state with no recent decisions names pipeline recency", async ({ page }) => {
  await mockActionable(page, {
    items: [],
    count: 0,
    available: true,
    raw_count: 0,
    shown: 0,
    source: "queue",
    last_pipeline_run_at: "2026-08-25T18:47:46",
  });

  await page.goto("/paper", { waitUntil: "domcontentloaded" });

  const empty = page.getByTestId("actionable-empty");
  await expect(empty).toBeVisible();
  await expect(empty).toContainText("No recent directional decisions");
  await expect(empty).toContainText("pipeline last ran");
});

test("empty state with no pipeline run explains engine offline", async ({ page }) => {
  await mockActionable(page, {
    items: [],
    count: 0,
    available: true,
    raw_count: 0,
    shown: 0,
    source: "queue",
    last_pipeline_run_at: null,
  });

  await page.goto("/paper", { waitUntil: "domcontentloaded" });

  const empty = page.getByTestId("actionable-empty");
  await expect(empty).toBeVisible();
  await expect(empty).toContainText("pipeline is not running");
});

test("command-center page also mounts the actionable board", async ({ page }) => {
  await mockActionable(page, {
    items: [],
    count: 0,
    available: true,
    raw_count: 5,
    shown: 0,
    source: "queue",
    last_pipeline_run_at: "2026-08-25T18:47:46",
  });

  await page.goto("/command-center", { waitUntil: "domcontentloaded" });

  await expect(page.getByText(/Actionable Now/).first()).toBeVisible();
  const empty = page.getByTestId("actionable-empty");
  await expect(empty).toBeVisible();
  await expect(empty).toContainText("5 recent rows");
  await expect(empty, { timeout: 15_000 }).toContainText("none qualify as actionable");
});
