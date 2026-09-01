import test from "node:test";
import assert from "node:assert/strict";

import {
  executionCapability,
  type ControlPlaneSnapshot,
} from "@/lib/controlPlane";

function snapshot(overrides: Partial<ControlPlaneSnapshot> = {}): ControlPlaneSnapshot {
  return {
    fetchedAt: "2026-08-31T23:00:00.000Z",
    health: {
      status: "ok",
      live_trading: false,
      paper_mode: true,
      kill_switch_active: false,
      ibkr_connected: true,
      ibkr_execution_connected: true,
      ibkr_data_connected: true,
    },
    safety: {
      kill_switch_active: false,
      kill_switch_reason: null,
      live_trading_enabled: false,
      require_human_approval: true,
      daily_pnl: 0,
      max_daily_loss: -100,
      portfolio_equity: 3000,
      peak_equity: 3000,
      current_drawdown: 0,
      orders_today: 0,
      drawdown_pct: 0,
      drawdown_limit_pct: -0.2,
      drawdown_breached: false,
    },
    portfolio: {
      total_equity: 3000,
      unrealized_pnl: 0,
      realized_pnl: 0,
      daily_pnl: 0,
      margin_used: 0,
      margin_available: 3000,
      positions: [],
    },
    portfolioRisk: {},
    pendingApprovals: { count: 0, candidates: [] },
    paperStatus: {},
    errors: {},
    ...overrides,
  };
}

test("healthy paper state permits paper approval capability", () => {
  const result = executionCapability(snapshot());
  assert.equal(result.mode, "PAPER");
  assert.equal(result.canApprovePaper, true);
  assert.deepEqual(result.reasons, []);
});

test("live mode is never treated as paper approval capable", () => {
  const base = snapshot();
  const result = executionCapability(
    snapshot({
      health: { ...base.health!, live_trading: true, paper_mode: false },
      safety: { ...base.safety!, live_trading_enabled: true },
    }),
  );
  assert.equal(result.mode, "LIVE");
  assert.equal(result.canApprovePaper, false);
  assert.ok(result.reasons.some((reason) => reason.includes("LIVE")));
});

test("kill switch disables approval capability", () => {
  const base = snapshot();
  const result = executionCapability(
    snapshot({ safety: { ...base.safety!, kill_switch_active: true } }),
  );
  assert.equal(result.canApprovePaper, false);
  assert.ok(result.reasons.includes("kill switch active"));
});

test("missing IB execution connection disables approval capability", () => {
  const base = snapshot();
  const result = executionCapability(
    snapshot({
      health: {
        ...base.health!,
        ibkr_connected: false,
        ibkr_execution_connected: false,
      },
    }),
  );
  assert.equal(result.canApprovePaper, false);
  assert.ok(result.reasons.includes("IBKR execution connection unavailable"));
});

test("degraded cockpit state fails closed", () => {
  const result = executionCapability(
    snapshot({ errors: { portfolioRisk: "Engine error 503: /portfolio/risk" } }),
  );
  assert.equal(result.canApprovePaper, false);
  assert.ok(result.reasons.includes("cockpit state is degraded"));
});

test("drawdown breach disables approval capability", () => {
  const base = snapshot();
  const result = executionCapability(
    snapshot({ safety: { ...base.safety!, drawdown_breached: true } }),
  );
  assert.equal(result.canApprovePaper, false);
  assert.ok(result.reasons.includes("drawdown limit breached"));
});
