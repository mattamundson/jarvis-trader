import test from "node:test";
import assert from "node:assert/strict";

import {
  candidateApprovalCapability,
  candidateTradeTerms,
  executionCapability,
  type ControlPlaneApproval,
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

function candidate(overrides: Partial<ControlPlaneApproval> = {}): ControlPlaneApproval {
  return {
    id: 7,
    created_at: "2026-08-31T22:55:00.000Z",
    symbol: "MES",
    direction: "LONG",
    confidence: 0.74,
    expires_at: "2026-09-01T00:30:00.000Z",
    status: "pending",
    stark_signal: "MOM_BREAKOUT_V4",
    validation_only: false,
    verdict: {
      trade_decision: {
        entry_price: 6500,
        stop_price: 6498,
        target_1: 6504,
        quantity: 1,
      },
      fund_decision: { final_quantity: 2 },
    },
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

test("candidate terms mirror server precedence and compute R:R", () => {
  const terms = candidateTradeTerms(candidate());
  assert.equal(terms.side, "LONG");
  assert.equal(terms.entryPrice, 6500);
  assert.equal(terms.stopPrice, 6498);
  assert.equal(terms.targetPrice, 6504);
  assert.equal(terms.quantity, 2, "fund_decision.final_quantity wins over trade quantity");
  assert.equal(terms.riskPointsPerUnit, 2);
  assert.equal(terms.rewardPointsPerUnit, 4);
  assert.equal(terms.rewardRisk, 2);
});

test("valid frozen candidate is paper-approvable when global cockpit is healthy", () => {
  const result = candidateApprovalCapability(snapshot(), candidate(), Date.parse("2026-08-31T23:15:00Z"));
  assert.equal(result.canApprove, true);
  assert.deepEqual(result.reasons, []);
});

test("validation-only candidate is blocked client-side as well as server-side", () => {
  const result = candidateApprovalCapability(
    snapshot(),
    candidate({ validation_only: true }),
    Date.parse("2026-08-31T23:15:00Z"),
  );
  assert.equal(result.canApprove, false);
  assert.ok(result.reasons.includes("strategy is validation-only"));
});

test("expired candidate is blocked", () => {
  const result = candidateApprovalCapability(
    snapshot(),
    candidate({ expires_at: "2026-08-31T23:00:00Z" }),
    Date.parse("2026-08-31T23:15:00Z"),
  );
  assert.equal(result.canApprove, false);
  assert.ok(result.reasons.includes("candidate expired"));
});

test("candidate without a protective stop or target fails closed", () => {
  const result = candidateApprovalCapability(
    snapshot(),
    candidate({
      verdict: {
        trade_decision: { entry_price: 6500, quantity: 1 },
        fund_decision: { final_quantity: 1 },
      },
    }),
    Date.parse("2026-08-31T23:15:00Z"),
  );
  assert.equal(result.canApprove, false);
  assert.ok(result.reasons.includes("protective stop unavailable"));
  assert.ok(result.reasons.includes("target unavailable"));
});

test("wrong LONG stop/target geometry fails closed", () => {
  const result = candidateApprovalCapability(
    snapshot(),
    candidate({
      verdict: {
        trade_decision: {
          entry_price: 6500,
          stop_price: 6501,
          target_1: 6499,
          quantity: 1,
        },
      },
    }),
    Date.parse("2026-08-31T23:15:00Z"),
  );
  assert.equal(result.canApprove, false);
  assert.ok(result.reasons.includes("LONG stop must be below entry"));
  assert.ok(result.reasons.includes("LONG target must be above entry"));
});

test("global safety failure also blocks an otherwise valid candidate", () => {
  const base = snapshot();
  const result = candidateApprovalCapability(
    snapshot({ safety: { ...base.safety!, kill_switch_active: true } }),
    candidate(),
    Date.parse("2026-08-31T23:15:00Z"),
  );
  assert.equal(result.canApprove, false);
  assert.ok(result.reasons.includes("kill switch active"));
});
