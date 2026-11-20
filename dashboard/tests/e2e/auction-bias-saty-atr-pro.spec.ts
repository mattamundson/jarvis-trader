import { test, expect } from "@playwright/test";

const AUCTION_PAYLOAD = {
  symbol: "MES",
  available: true,
  price: 7526.75,
  prior_close: 7551.75,
  saty: {
    atr: 102.161,
    call_trigger: 7575.86,
    put_trigger: 7527.64,
    plus_1_atr: 7653.91,
    minus_1_atr: 7449.59,
    bias: "short",
    trigger_state: "downside_trigger",
    range_state: "initiative_down",
    chase_risk: true,
    atr_displacement: -0.245,
    gap_atr: null,
    day_range_pct_of_atr: 0.925,
    context_score: { up: 0, down: 0 },
    next_levels: { up: 7575.86, down: 7512.72 },
  },
  tpo: { value_area: 7500, profile_target: 7624.25, fail_target: 7529.75, failed: true },
  corey: { bias: "bearish", data_quality: "stale" },
  synthesis: {
    line_in_sand: 7530.75,
    line_source: "corey_buyers_offside",
    long_above: 7530.75,
    short_below: 7530.75,
    confirm_long_above: 7546.25,
    confirm_short_below: 7512.72,
    lean: "short intraday / flat overnight",
    overnight_recommendation: "no-edge / stand aside — range exhausted, do not carry direction overnight",
  },
  engine_derived: true,
  chart_parity: false,
  caveats: ["day range 93% of ATR — exhausted"],
  provenance: { is_live: true, source: "ibkr", as_of: 1789082625, stale_after_s: 120 },
};

test("analysis page renders Saty ATR Pro context as read-only decision support", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => route.fulfill({ status: 200, json: {} }));
  await page.route("**/api/engine/auction/bias/MES", (route) => route.fulfill({ status: 200, json: AUCTION_PAYLOAD }));

  await page.goto("/analysis", { waitUntil: "domcontentloaded" });

  await expect(page.getByText("MES Auction Bias")).toBeVisible();
  await expect(page.getByText("Saty ATR Pro context")).toBeVisible();
  await expect(page.getByText("CHASE RISK")).toBeVisible();
  await expect(page.getByText("Displacement")).toBeVisible();
  await expect(page.getByText("Range state")).toBeVisible();
  await expect(page.getByText("Trigger state")).toBeVisible();
  await expect(page.getByText("neutral read-only map, not an execution signal")).toBeVisible();
  await expect(page.getByRole("button", { name: /submit|order|trade/i })).toHaveCount(0);
});
