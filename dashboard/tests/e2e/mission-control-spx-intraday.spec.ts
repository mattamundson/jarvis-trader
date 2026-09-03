import { test, expect } from "@playwright/test";

const SPX_PAYLOAD = {
  mode: "ANALYSIS_ONLY",
  orders_enabled: false,
  risk_config_touched: false,
  asOf: "2026-09-03T20:35:00.000Z",
  symbol: "SPX",
  proxyUsed: "SPX_DIRECT",
  sourceQuality: "fresh",
  currentPrice: 7749.78,
  dayHigh: 7756.76,
  dayLow: 7686.71,
  dayChangePct: 1.08,
  previousClose: 7666.6,
  vix: 14.41,
  vixChangePct: -5.2,
  rsi14: 43.9,
  ema9: 7750.26,
  ema21: 7750.46,
  sma50: 7751.44,
  vwap: 7730.59,
  returns: { fiveMinPct: -0.012, fifteenMinPct: -0.01, thirtyMinPct: -0.031, sixtyMinPct: -0.067 },
  breadth: { spyPct: 1.08, qqqPct: 1.17, rspPct: 0.65, iwmPct: 0.33, spyRspSpread: 0.43, qqqIwmSpread: 0.84, sectorsGreen: 8, sectorsTotal: 11 },
  levels: [
    { label: "Day high / upside reclaim", value: 7756.76, distance: -6.98, status: "below", role: "target" },
    { label: "Immediate breakout support", value: 7752.01, distance: -2.23, status: "lost", role: "pivot" },
    { label: "Last breakout shelf", value: 7749.78, distance: 0, status: "at", role: "pivot" },
    { label: "Buyer-control line", value: 7743.84, distance: 5.94, status: "above", role: "support" },
  ],
  probabilityBands: {
    p10: 7743.85,
    p25: 7746.43,
    p50: 7749.78,
    p75: 7752.18,
    p90: 7755.09,
    closeAbove: { "7749.78": 48.1, "7752.01": 33.4, "7743.84": 90.2 },
    closeBelow: { "7749.78": 51.9, "7752.01": 66.6, "7743.84": 9.8 },
    touchAbove: { "7752.01": 66.8 },
    touchBelow: { "7743.84": 24.5 },
    remainingMinutes: 24,
    blendedSigmaPoints: 4.6,
  },
  scenarios: [
    { id: "pin_chop", label: "Pin / chop around pivot", probability: 45, expectedCloseBand: [7748, 7752], trigger: "pivot", invalidation: "break" },
    { id: "breakout_failure", label: "Breakout failure / buyer-control test", probability: 30, expectedCloseBand: [7741, 7748], trigger: "below pivot", invalidation: "reclaim" },
  ],
  verdict: {
    label: "BREAKOUT_FAILURE_TEST",
    confidence: 0.68,
    summary: "SPX lost 7752.01 and is testing the 7749.78 breakout shelf; 7743.84 is the downside magnet unless 7752.01 is reclaimed.",
    bullEvidence: ["VIX soft at 14.41"],
    bearEvidence: ["7752.01 breakout support is lost"],
    invalidation: ["Bullish save requires sustained trade above 7752.01"],
  },
  warnings: [],
  modelVersion: "spx-intraday-dashboard-v1",
};

test("mission control renders SPX intraday analysis as analysis-only", async ({ page }) => {
  await page.route("**/api/spx-intraday", (route) => route.fulfill({ status: 200, json: SPX_PAYLOAD }));
  await page.route("**/api/engine/**", (route) => route.fulfill({ status: 200, json: {} }));
  await page.route("**/api/fleet", (route) => route.fulfill({ status: 200, json: { loops: [], agents: [], updated_at: null } }));

  await page.goto("/mission-control", { waitUntil: "domcontentloaded" });

  const card = page.getByTestId("spx-intraday-analysis-card");
  await expect(card).toBeVisible();
  await expect(card.getByText("SPX Intraday Decision")).toBeVisible();
  await expect(card.getByText("ANALYSIS ONLY")).toBeVisible();
  await expect(card.getByText("BREAKOUT FAILURE TEST")).toBeVisible();
  await expect(card.getByText("Level ladder")).toBeVisible();
  await expect(card.getByText("Probability map")).toBeVisible();
  await expect(card.getByRole("button", { name: /submit|order|trade/i })).toHaveCount(0);
});
