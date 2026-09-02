import { test, expect } from "@playwright/test";

// P9-3: /trading-eligibility mounts the new TradingStatusReconciliation panel
// (P8-tradingstatus, dashboard/components/TradingStatusReconciliation.tsx),
// a thin render of GET /trading-status -- the engine's server-side merge of
// PAPER_CONFIGS.enabled x DO_NOT_TRADE_SYMBOLS x the latest gate-v2 verdict
// (services/trading_status.py, Phase 1c). This is the exact defect class the
// MES gate-v2 bypass (PR #564) showed the runtime cost of: a symbol whose
// three authorities disagree can silently trade when it shouldn't, or fail to
// trade when it should. This spec locks in that a disagreeing row renders an
// unmissable SPLIT-BRAIN warn badge and its listed reason -- not just "the
// page loaded".
test("trading-eligibility renders a SPLIT-BRAIN warn badge and reason for a disagreeing symbol", async ({
  page,
}) => {
  await page.route("**/api/engine/**", (route) => {
    const u = route.request().url();
    if (u.includes("/trading-status")) {
      return route.fulfill({
        status: 200,
        json: {
          summary: { total: 2, tradeable: 1, enabled: 2, disagreements: 1 },
          symbols: [
            {
              symbol: "MGC",
              enabled: true,
              authorized: false,
              verdict: "PASS",
              verdict_family: "atr_trail",
              verdict_created_at: "2026-07-20T00:00:00Z",
              verdict_age_days: 13,
              oos_trades: 61,
              tradeable: false,
              config_agrees: false,
              disagreements: [
                "PAPER_CONFIGS.enabled=true but DO_NOT_TRADE_SYMBOLS blocks MGC",
              ],
            },
            {
              symbol: "MES",
              enabled: true,
              authorized: true,
              verdict: "PASS",
              verdict_family: "atr_trail",
              verdict_created_at: "2026-07-25T00:00:00Z",
              verdict_age_days: 8,
              oos_trades: 90,
              tradeable: true,
              config_agrees: true,
              disagreements: [],
            },
          ],
        },
      });
    }
    // /paper/validation/approved-paper-gates -- the page's own primary data
    // source, unrelated to the reconciliation panel under test here. eligibilityRows()
    // guards `!data?.instruments` -> [], so an empty object is a safe, realistic
    // "no gate data" shape.
    if (u.includes("/paper/validation/approved-paper-gates")) {
      return route.fulfill({ status: 200, json: {} });
    }
    return route.fulfill({ status: 200, json: {} });
  });

  await page.goto("/trading-eligibility", { waitUntil: "networkidle" });

  const body = (await page.textContent("body")) || "";
  expect(body, "page did not render the Trading Eligibility header").toContain(
    "Trading Eligibility"
  );

  const mgcRow = page.locator("div", { hasText: /^MGC/ }).filter({ hasText: "SPLIT-BRAIN" }).first();
  await expect(mgcRow, "MGC's split-brain row did not render a SPLIT-BRAIN badge").toBeVisible();
  await expect(
    page.getByText("PAPER_CONFIGS.enabled=true but DO_NOT_TRADE_SYMBOLS blocks MGC"),
    "the specific disagreement reason was not rendered"
  ).toBeVisible();

  // The panel's own header badge summarizes the disagreement count.
  await expect(page.getByText("1 split-brain")).toBeVisible();

  // The agreeing symbol (MES) must NOT carry the same warning.
  const mesRow = page.locator("div", { hasText: /^MES/ }).first();
  await expect(mesRow.getByText("SPLIT-BRAIN")).toHaveCount(0);
});
