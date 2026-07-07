import { test, expect } from "@playwright/test";

// Golden path: under DEGRADED engine data (null prices + sparse/empty payloads)
// the overview must still render its core content and NEVER white-screen.
//
// What this guarded originally (#163): SignalFlowWidget renders the em-dash
// for null prices instead of crashing on `null.toLocaleString()`, asserted via
// its "instruments: MCL / MNQ / MES" footer text.
//
// STALE AS OF P2.1 (commit d4b1ab1, discovered while working P5.2): `/` now
// redirects to the flagship `/command-center`, which does not mount
// SignalFlowWidget at all -- `components/widgets/SignalFlowWidget.tsx` has
// zero importers anywhere in the tree (grep-verified). The #163 regression
// this test named is no longer exercised by ANY reachable route; this is an
// orphaned-component finding for a future cleanup item (P1.5-style dead-code
// sweep), left untouched here per meta-discipline (don't delete code you
// didn't author without an explicit item). This test is repointed at the
// flagship's own degraded-data resilience (navigating there directly, same
// destination `/` now redirects to) so it keeps asserting something true
// instead of silently passing on unreachable text.
const NULL_PRICE = { last_price: null, prev_close: null, change_pct: null, error: "No data available" };

test("overview survives degraded engine data without white-screening", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => {
    const u = route.request().url();
    if (u.includes("/prices/snapshot")) {
      return route.fulfill({
        json: { MCL: { symbol: "MCL", ...NULL_PRICE }, MNQ: { symbol: "MNQ", ...NULL_PRICE }, MES: { symbol: "MES", ...NULL_PRICE } },
      });
    }
    // Since P2.1 (commit d4b1ab1), `/` redirects to the flagship
    // `/command-center`, which -- unlike the old kitchen-sink page -- reads
    // these three as arrays and `journalStats.diagnosis` unconditionally on
    // a truthy-but-empty response. See command-center-golden-path.spec.ts
    // for the full explanation of each mocked shape.
    if (u.includes("/decisions/recent") || u.includes("/portfolio/history/trades")) {
      return route.fulfill({ status: 200, json: [] });
    }
    if (u.includes("/scheduler/status")) {
      return route.fulfill({ status: 200, json: { jobs: [] } });
    }
    if (u.includes("/journal/review/stats")) {
      return route.fulfill({
        status: 200,
        json: {
          total_trades: 0,
          win_rate: 0,
          avg_win_usd: 0,
          avg_loss_usd: 0,
          risk_reward_ratio: 0,
          expected_value_usd: 0,
          trades_per_week: 0,
          diagnosis: "insufficient_data",
        },
      });
    }
    return route.fulfill({ status: 200, json: {} });
  });

  await page.goto("/command-center", { waitUntil: "networkidle" });
  const body = (await page.textContent("body")) || "";

  expect(body, "flagship header did not render").toContain("COMMAND CENTER");
  // The page did NOT collapse to the route-level error fallback (no white-screen).
  expect(body, "page white-screened to the route error fallback").not.toMatch(/something went wrong/i);
});
