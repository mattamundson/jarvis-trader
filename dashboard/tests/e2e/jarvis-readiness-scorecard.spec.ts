import { test, expect } from "@playwright/test";

test("readiness scorecard API returns read-only contract", async ({ request }) => {
  const response = await request.get("/api/jarvis/readiness-scorecard");
  expect(response.ok()).toBeTruthy();
  const payload = await response.json();

  expect(payload.schema_version).toBe("jarvis-readiness-scorecard.v1");
  expect(payload.mode).toBe("READ_ONLY_ANALYSIS");
  expect(payload.safety.live_trading_changed).toBe(false);
  expect(payload.safety.risk_config_changed).toBe(false);
  expect(payload.safety.kill_switch_changed).toBe(false);
  expect(payload.safety.broker_execution_changed).toBe(false);
  expect(payload.badges.edge_certified).toBe(false);
  expect(payload.metrics.unique_linked_paper_trades).toBe(62);
  expect(payload.metrics.queue_order_id_matches_to_paper).toBe(0);
  expect(payload.metrics.linked_vs_unlinked_pnl_delta).toBe(6336);
});

test("jarvis page renders readiness scorecard split badges", async ({ page }) => {
  await page.route("**/api/engine/**", (route) =>
    route.fulfill({ status: 503, json: { detail: "engine unavailable in smoke" } })
  );

  await page.route("**/api/jarvis/readiness-scorecard", (route) =>
    route.fulfill({
      status: 200,
      json: {
        schema_version: "jarvis-readiness-scorecard.v1",
        generated_at: "2026-09-12T08:49:50.403936+00:00",
        mode: "READ_ONLY_ANALYSIS",
        badges: {
          operator_analysis_ready: true,
          monitoring_ready: false,
          execution_ready: false,
          recommendation_attribution_proven: true,
          queue_order_lineage_proven: false,
          edge_certified: false,
        },
        metrics: {
          dashboard_ok: true,
          engine_ok: true,
          current_actionable_shown: null,
          current_actionable_raw: null,
          pending_approvals: null,
          unique_linked_paper_trades: 62,
          linked_rth_paper_trades: 20,
          queue_order_id_matches_to_paper: 0,
          linked_closed_pnl: 4758.66,
          linked_profit_factor: 2.3703,
          rth_linked_closed_pnl: 1885.33,
          rth_linked_profit_factor: 5.9318,
          linked_vs_unlinked_pnl_delta: 6336.0,
          linked_vs_all_paper_avg_trade_delta: 78.34,
        },
        blockers: ["kill_switch_active=true", "live_trading=false"],
        display_notes: ["No execution changes."],
      },
    })
  );

  await page.goto("/jarvis");

  await expect(page.getByText("Readiness Scorecard")).toBeVisible();
  await expect(page.getByText("operator analysis ready")).toBeVisible();
  await expect(page.getByText("monitoring degraded")).toBeVisible();
  await expect(page.getByText("execution blocked")).toBeVisible();
  await expect(page.getByText("recommendation linked")).toBeVisible();
  await expect(page.getByText("queue lineage gap")).toBeVisible();
  await expect(page.getByText("edge not certified")).toBeVisible();
  await expect(page.getByText("Baseline delta")).toBeVisible();
  await expect(page.getByText("$6,336")).toBeVisible();
  await expect(page.getByText("62")).toBeVisible();
  await expect(page.getByText("$4,759")).toBeVisible();
  await expect(page.getByText("Read-only scorecard")).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/something went wrong/i);
});
