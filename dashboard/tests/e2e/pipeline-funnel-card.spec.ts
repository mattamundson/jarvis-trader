import { test, expect } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";
import { installEngineMock } from "./_engineMock";

// The dashboard enforces Basic Auth locally (DASHBOARD_AUTH_USER/PASS in
// .env.local via middleware.ts). Read the creds ourselves so the fresh-port
// run (port 3013, which loads .env.local) can authenticate; never print them.
function loadCreds(): { user: string; pass: string } | null {
  const p = path.resolve(__dirname, "../../.env.local");
  if (!fs.existsSync(p)) return null;

  let user = "", pass = "";
  for (const line of fs.readFileSync(p, "utf8").split("\n")) {
    const m = line.match(/^DASHBOARD_AUTH_USER=(.*)$/);
    if (m) user = m[1].trim();
    const m2 = line.match(/^DASHBOARD_AUTH_PASS=(.*)$/);
    if (m2) pass = m2[1].trim();
  }
  return user && pass ? { user, pass } : null;
}

const FUNNEL_30 = {
  days: 30,
  cutoff_utc: "2026-07-26T00:00:00",
  runs: 4778,
  signals: 284,
  auto_signals: 158,
  human_signals: 126,
  queue_approved_raw: 1,
  approved: 159,
  executed: 28,
  filled: 28,
  conversion: {
    signal_rate_pct: 5.94,
    approval_rate_pct: 55.99,
    execution_rate_pct: 17.61,
    fill_rate_pct: 100.0,
    overall_fill_rate_pct: 0.59,
  },
  notes: [],
};

const FUNNEL_90 = {
  days: 90,
  cutoff_utc: "2026-05-27T00:00:00",
  runs: 11163,
  signals: 1830,
  auto_signals: 1533,
  human_signals: 297,
  queue_approved_raw: 387,
  approved: 1830,
  executed: 116,
  filled: 87,
  conversion: {
    signal_rate_pct: 16.39,
    approval_rate_pct: 100.0,
    execution_rate_pct: 6.34,
    fill_rate_pct: 75.0,
    overall_fill_rate_pct: 0.78,
  },
  notes: [
    "approval ledger (387) exceeds human-required signals (297) — queue rows without matching decision rows; approved is capped at signals.",
  ],
};

test("command-center renders the Pipeline Funnel card with 30/90d conversion", async ({ browser }) => {
  const creds = loadCreds();
  const context = await browser.newContext(
    creds ? { httpCredentials: { username: creds.user, password: creds.pass } } : {},
  );
  const page = await context.newPage();

  // Shape-aware degraded mock for every engine endpoint ([] for list
  // endpoints, declared contracts for known shapes -- a blanket `{}` makes
  // unrelated widgets crash on .slice()/.map() and masks the assertion this
  // spec exists to make; see _engineMock.ts).
  await installEngineMock(page, "degraded");

  // Route ordering matters: Playwright evaluates handlers in REVERSE
  // registration order (last registered wins), so the funnel-specific mock
  // must be registered AFTER installEngineMock's catch-all.
  await page.route("**/api/engine/analytics/pipeline-funnel*", (route) =>
    route.fulfill({
      status: 200,
      json: {
        generated_at: "2026-08-25T19:00:00.000000+00:00",
        cache_ttl_seconds: 300,
        windows: { "30": FUNNEL_30, "90": FUNNEL_90 },
      },
    })
  );

  await page.goto("/command-center", { waitUntil: "domcontentloaded" });

  const card = page.getByTestId("pipeline-funnel-card");
  await expect(card).toBeVisible({ timeout: 15000 });

  // Both windows render with counts.
  await expect(page.getByTestId("pipeline-funnel-30d")).toContainText("4,778");
  await expect(page.getByTestId("pipeline-funnel-90d")).toContainText("11,163");

  // Stage labels + overall conversion headline (used by the live checker).
  await expect(card).toContainText("OVERALL CONVERSION");
  await expect(card).toContainText("SIGNALS");
  await expect(card).toContainText("APPROVED");
  await expect(card).toContainText("EXECUTED");
  await expect(card).toContainText("FILLED");

  // Ledger-drift note is surfaced, not hidden.
  await expect(card).toContainText("approval ledger (387)");

  await context.close();
});
