import { test, expect } from "@playwright/test";

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

test("command-center renders the Pipeline Funnel card with 30/90d conversion", async ({ page }) => {
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
  // Let every other engine call resolve empty so the page mounts cleanly.
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
});
