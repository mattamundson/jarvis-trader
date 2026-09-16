import { expect, test } from "@playwright/test";

const snapshot = {
  schema_version: 1,
  generated_at: Math.floor(Date.now() / 1000),
  quote_ts: Math.floor(Date.now() / 1000) - 900,
  data_delayed_minutes: 15,
  stale_after_s: 2700,
  data_quality: "ok",
  errors: [],
  disclaimer: "Market-implied analytics from delayed quotes — no validated predictive edge, not trade signals.",
  regime: {
    vix: 17.84,
    vix3m: 19.73,
    slope: 0.0189,
    regime: "CONTANGO",
    vix_percentile_1y: 0.5952,
    as_of_date: "2026-09-10",
    source: "test",
  },
  symbols: {
    SPY: {
      spot: 765.21,
      quote_ts: Math.floor(Date.now() / 1000) - 900,
      horizons: [
        {
          label: "nearest",
          expiry: "2026-09-18",
          dte_calendar: 7,
          atm_strike: 765,
          atm_iv: 0.1135,
          straddle_mid: 10.41,
          expected_move_abs: 10.41,
          expected_move_pct: 0.013604,
          prob_ladder: [
            { multiple: 1, label: "+1.0 EM", level: 775.62, p_above: 0.1613, p_touch: 0.3227, p_fail: 0.6773 },
            { multiple: 0, label: "spot", level: 765.21, p_above: 0.5144, p_touch: 1, p_fail: 0 },
          ],
          opportunity_board: {
            symbol: "SPY",
            expiry: "2026-09-18",
            spot: 765.21,
            status: "ok",
            source: "CBOE delayed quotes",
            source_confidence: 0.9846,
            source_notes: ["CBOE 15-minute delayed chain", "1 accepted / 1 rejected candidates"],
            candidate_count: 1,
            rejected_count: 1,
            candidates: [
              {
                structure: "BEAR_PUT_DEBIT_SPREAD",
                thesis: "downside participation with bounded debit risk",
                net_price: 2.37,
                max_loss: 237,
                max_gain: 363,
                breakeven: 763.63,
                pop: 0.4339,
                ev: 23.35,
                ev_to_max_loss: 0.0985,
                reward_to_risk: 1.5316,
                liquidity_score: 0.9846,
                score: 0.5931,
                reject_reasons: [],
                journal_url: "/journal?source=options-opportunity-board",
                journal_note: "ANALYSIS_ONLY options review: SPY BEAR PUT DEBIT SPREAD exp 2026-09-18",
              },
            ],
            rejected_candidates: [
              {
                structure: "PUT_CREDIT_SPREAD",
                thesis: "defined-risk bullish/neutral premium sale",
                net_price: 0.98,
                max_loss: 502,
                max_gain: 98,
                breakeven: 755.02,
                pop: 0.7764,
                ev: -36.14,
                ev_to_max_loss: -0.072,
                reward_to_risk: 0.1952,
                liquidity_score: 0.9858,
                score: 0.3023,
                reject_reasons: ["reward/risk below floor"],
              },
            ],
            reject_summary: [],
            disclaimer: "Analysis-only defined-risk board from delayed options quotes; not a trade signal.",
          },
          quality: "ok",
          notes: [],
        },
      ],
    },
  },
};

test("signals options panel renders defined-risk opportunity board", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => {
    const url = route.request().url();
    if (url.includes("/api/engine/options-signals/latest")) {
      return route.fulfill({ status: 200, json: snapshot });
    }
    if (url.includes("/api/engine/approvals/pending")) {
      return route.fulfill({ status: 200, json: { count: 0, candidates: [] } });
    }
    if (url.includes("/api/engine/approvals/history")) {
      return route.fulfill({ status: 200, json: { days: 7, count: 0, history: [] } });
    }
    return route.fulfill({ status: 200, json: {} });
  });

  await page.goto("/signals", { waitUntil: "domcontentloaded" });

  await expect(page.getByText("SPY/QQQ Options — Market-Implied")).toBeVisible();
  await expect(page.getByText(/FRESH SNAPSHOT/)).toBeVisible();
  await expect(page.getByText(/Market-implied decision support only/)).toBeVisible();
  await expect(page.getByText(/no edge, fillability, or executable quote is claimed/)).toBeVisible();
  await expect(page.getByText("Defined-risk opportunity board · ANALYSIS_ONLY")).toBeVisible();
  await expect(page.getByText("BEAR PUT DEBIT SPREAD")).toBeVisible();
  await expect(page.getByText("journal handoff")).toBeVisible();
  await expect(page.getByText("SRC 98%")).toBeVisible();
  await expect(page.getByText(/Source: CBOE delayed quotes/)).toBeVisible();
  await expect(page.getByText("EV/MAX LOSS")).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "P(TOUCH)" })).toBeVisible();
});
