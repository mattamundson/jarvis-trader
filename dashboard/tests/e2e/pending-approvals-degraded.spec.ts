import { test, expect } from "@playwright/test";

// P9-3: /trades/pending-approvals is where a human signs off on a real trade.
// The risk-summary base figure (position-size %, margin-impact %) is computed
// against account equity from GET /safety/status. When that endpoint is
// unreachable, app/trades/pending-approvals/page.tsx:66-70 falls back to a
// hardcoded ACCOUNT_VALUE_FALLBACK ($10,000) -- see component test
// tests/component/PendingApprovalsConfirm.test.tsx for the same contract at
// the unit level. This spec locks in the SAME honesty behavior end to end
// through the real /api/engine proxy: the fallback figure must always render
// a visible "(default -- engine offline)" label next to it, never silently
// as if it were the real live account value.
test("pending-approvals shows the $10,000 fallback base labelled as non-live when /safety/status is unreachable", async ({
  page,
}) => {
  await page.route("**/api/engine/**", (route) => {
    const u = route.request().url();
    if (u.includes("/pipeline/pending-approvals")) {
      return route.fulfill({
        status: 200,
        json: {
          pending: [
            {
              id: 1,
              approval_id: "approval-e2e-1",
              symbol: "MES",
              action: "BUY",
              quantity: 2,
              entry_price: 5000,
              created_at: "2026-08-02T00:00:00Z",
              pipeline_snapshot: null,
              status: "pending",
              resolved_at: null,
              resolved_by: null,
              rejection_reason: null,
              paper_trade_id: null,
              ib_order_id: null,
            },
          ],
          count: 1,
        },
      });
    }
    // /safety/status unreachable -- the exact degraded condition this spec covers.
    if (u.includes("/safety/status")) {
      return route.fulfill({ status: 503, json: { detail: "safety status unavailable" } });
    }
    // ActionableBoardWidget (separate live-status board mounted above the
    // queue) -- 404 so it renders its own "unreachable" note rather than
    // tripping on an unrealistic shape.
    if (u.includes("/pipeline/actionable")) {
      return route.fulfill({ status: 404, json: { detail: "not found" } });
    }
    return route.fulfill({ status: 200, json: {} });
  });

  await page.goto("/trades/pending-approvals", { waitUntil: "networkidle" });

  const body = (await page.textContent("body")) || "";
  expect(body, "page did not render the pending-approvals header").toContain(
    "Pending trade approvals"
  );

  // The exact risk-summary base line: "base $10,000 (default — engine offline)".
  const baseLine = page.locator("p", { hasText: "base $10,000" });
  await expect(baseLine, "fallback account-value base line did not render").toBeVisible();
  await expect(baseLine).toContainText("(default — engine offline)");
  await expect(baseLine, "fallback figure was rendered without its non-live marker").not.toContainText(
    "(live)"
  );

  // The margin-impact figure's own approximation badge (independent of the
  // account-value fallback above -- a flat-5% heuristic, not a real margin
  // lookup) must also be visible.
  await expect(page.getByText("Static", { exact: true }).first()).toBeVisible();
});

test("pending-approvals shows the live equity base, unmarked as fallback, once /safety/status reports real equity", async ({
  page,
}) => {
  await page.route("**/api/engine/**", (route) => {
    const u = route.request().url();
    if (u.includes("/pipeline/pending-approvals")) {
      return route.fulfill({
        status: 200,
        json: {
          pending: [
            {
              id: 1,
              approval_id: "approval-e2e-2",
              symbol: "MGC",
              action: "SELL",
              quantity: 1,
              entry_price: 2400,
              created_at: "2026-08-02T00:00:00Z",
              pipeline_snapshot: null,
              status: "pending",
              resolved_at: null,
              resolved_by: null,
              rejection_reason: null,
              paper_trade_id: null,
              ib_order_id: null,
            },
          ],
          count: 1,
        },
      });
    }
    if (u.includes("/safety/status")) {
      return route.fulfill({
        status: 200,
        json: {
          kill_switch_active: false,
          kill_switch_reason: null,
          live_trading_enabled: true,
          require_human_approval: true,
          daily_pnl: 0,
          max_daily_loss: -500,
          portfolio_equity: 25000,
          peak_equity: 25000,
          current_drawdown: 0,
          orders_today: 0,
        },
      });
    }
    if (u.includes("/pipeline/actionable")) {
      return route.fulfill({ status: 404, json: { detail: "not found" } });
    }
    return route.fulfill({ status: 200, json: {} });
  });

  await page.goto("/trades/pending-approvals", { waitUntil: "networkidle" });

  const baseLine = page.locator("p", { hasText: "base $25,000" });
  await expect(baseLine, "live account-value base line did not render").toBeVisible();
  await expect(baseLine).toContainText("(live)");
  await expect(baseLine, "live figure was incorrectly marked as the engine-offline fallback").not.toContainText(
    "engine offline"
  );
});
