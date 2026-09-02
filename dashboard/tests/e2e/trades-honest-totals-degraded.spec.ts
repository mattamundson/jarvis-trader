import { test, expect } from "@playwright/test";

// P9-3: /trades ("Trade History") shows two different trade aggregates —
// the raw /paper/validation/trades/closed table (over-counts re-logged
// winners, per lib/honestTrades.ts's header comment) and the "Honest Totals"
// summary above it, sourced from master-api's deduped
// /master/trading/realized record via lib/honestTrades.ts fetchHonestTrades().
// fetchHonestTrades() THROWS when the engine-sim record reports
// `engine_sim.ok !== true` -- isHonestUnavailable() (lib/honestTrades.ts) is
// the single source of truth every consumer must gate on, specifically so a
// failed fetch can never silently render as a real (misleadingly precise)
// $0 / 0% row. This spec locks in that degraded path end to end: when
// master-api reports engine_sim.ok=false, the page must show the explicit
// "unavailable, not falling back to raw totals" message -- never a fabricated
// number in its place.
test("trade history shows the honest-unavailable message, never a fabricated total, when engine_sim.ok is false", async ({
  page,
}) => {
  await page.route("**/api/master/master/trading/realized**", (route) =>
    route.fulfill({
      status: 200,
      json: {
        engine_sim: { ok: false, error: "engine sim ledger unreachable" },
        ibkr_account: null,
        headline: "engine sim unavailable",
        caveats: [],
      },
    })
  );

  await page.route("**/api/engine/**", (route) => {
    const u = route.request().url();
    // Raw closed-trades table -- deliberately populated so the test proves
    // the honest-totals block degrades independently of the raw table (the
    // raw table's own disclaimer text only renders when trades.length > 0).
    if (u.includes("/paper/validation/trades/closed")) {
      return route.fulfill({
        status: 200,
        json: {
          trades: [
            {
              trade_id: "t1",
              symbol: "MES",
              direction: "LONG",
              entry_price: 5000,
              exit_price: 5010,
              pnl: 50,
              duration_seconds: 300,
              exit_time: "2026-08-01T00:00:00Z",
            },
          ],
        },
      });
    }
    if (u.includes("/execution/fidelity-status")) {
      return route.fulfill({ status: 200, json: { open_trades: [], measuring_real_fills: false } });
    }
    return route.fulfill({ status: 200, json: {} });
  });

  await page.goto("/trades", { waitUntil: "networkidle" });

  const body = (await page.textContent("body")) || "";
  expect(body, "page did not render the Trade History header").toContain("Trade History");

  await expect(
    page.getByText(
      "Honest trade record unavailable — not falling back to raw totals to avoid showing inflated numbers."
    ),
    "honest-unavailable message did not render"
  ).toBeVisible();

  // No fabricated headline number rendered in its place (the live-data grid
  // that would show Total/Wins/Losses/Win Rate/Total P&L stat tiles).
  await expect(page.getByText("Win Rate", { exact: true })).toHaveCount(0);

  // The raw table below still renders independently (it's a different data
  // source), proving the honest-totals degradation didn't take the whole
  // page down with it. Use a live locator: `body` was captured before the
  // asynchronous closed-trades response was guaranteed to have rendered.
  await expect(page.getByText(/Raw per-trade rows below/)).toBeVisible();
});
