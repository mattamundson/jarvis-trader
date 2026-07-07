import { test, expect } from "@playwright/test";

// Golden path: the overview's RollingWFEWidget must render the real
// per-instrument status states production actually produces -- not just the
// "everything is fine" happy path homepage-golden-path.spec.ts already covers.
//
// Per engine/CLAUDE.md, MCL and MNQ are HALTED (DO_NOT_TRADE_SYMBOLS, WFE
// divergence) and M2K was REJECTED before ever reaching paper trading. The
// widget's actual status vocabulary (WFEInstrument.status in lib/api.ts) is
// "healthy" | "warning" | "critical" | "insufficient_data" -- HALTED
// instruments surface as "critical" (bear badge); an instrument rejected
// before accumulating any live trades surfaces as "insufficient_data" (info
// badge), since it never had a WFE window to compute. This test locks in
// that both edge states render their badge and never white-screen the page,
// the same regression class #163/#207 guard for null prices.
//
// STALE AS OF P2.1 (commit d4b1ab1, discovered while working P5.2): `/` now
// redirects to the flagship `/command-center`. `components/RollingWFEWidget.tsx`
// has zero importers anywhere in the tree (grep-verified) -- it is not
// reachable via `/` or any other live route, so the CRITICAL/INSUFFICIENT
// badge assertions below no longer exercise real rendered output. Flagged as
// an orphaned-component finding for a future cleanup item (not deleted here
// per meta-discipline); this test is repointed at the flagship's own
// degraded-WFE-data resilience (navigating there directly, same destination
// `/` now redirects to) so it keeps asserting something true.
test("flagship survives degraded WFE (HALTED/never-traded instrument) data without crashing", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => {
    const u = route.request().url();
    if (u.includes("/paper/validation/wfe")) {
      return route.fulfill({
        json: {
          as_of: "2026-06-30T00:00:00Z",
          instruments: [
            {
              symbol: "MCL",
              current_wfe: 0.31,
              kill_threshold: 0.5,
              status: "critical",
              trades_in_window: 42,
              window_days: 30,
              current_pf: 0.71,
            },
            {
              symbol: "MNQ",
              current_wfe: 0.28,
              kill_threshold: 0.5,
              status: "critical",
              trades_in_window: 55,
              window_days: 30,
              current_pf: 0.64,
            },
            {
              symbol: "M2K",
              current_wfe: null,
              kill_threshold: 0.5,
              status: "insufficient_data",
              trades_in_window: 0,
              window_days: 30,
              current_pf: null,
            },
          ],
        },
      });
    }
    if (u.includes("/prices/snapshot")) {
      return route.fulfill({
        json: {
          MCL: { symbol: "MCL", last_price: 68.4, prev_close: 69.1, change_pct: -1.01 },
          MNQ: { symbol: "MNQ", last_price: 19850.5, prev_close: 19920.25, change_pct: -0.35 },
          MES: { symbol: "MES", last_price: 7459.25, prev_close: 7444.0, change_pct: 0.21 },
        },
      });
    }
    // See command-center-golden-path.spec.ts for the full explanation of
    // each mocked shape (decisions/trades/scheduler.jobs are array-typed;
    // journalStats.diagnosis is read unconditionally on a truthy response).
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
  // Page did not collapse to the route-level error fallback (no white-screen).
  expect(body, "page white-screened to the route error fallback").not.toMatch(/something went wrong/i);
});
