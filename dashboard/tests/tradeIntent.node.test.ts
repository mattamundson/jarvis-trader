import test from "node:test";
import assert from "node:assert/strict";

import {
  manualIntentCapability,
  type TradeIntentResponse,
} from "@/lib/tradeIntent";

function intent(overrides: Partial<TradeIntentResponse> = {}): TradeIntentResponse {
  return {
    intent_id: "intent-1",
    status: "PREVIEWED",
    preview: {
      symbol: "MES",
      direction: "BUY",
      order_type: "MARKET",
      entry_price: 6500,
      stop_loss: 6498,
      take_profit: 6504,
      account_equity: 3000,
      max_risk_fraction: 0.005,
      max_trade_loss_usd: 50,
      risk_budget_usd: 15,
      contract_multiplier: 5,
      risk_points_per_unit: 2,
      reward_points_per_unit: 4,
      dollar_risk_per_unit: 10,
      requested_quantity: 2,
      max_contracts: 2,
      final_quantity: 1,
      final_dollar_risk: 10,
      reward_risk_ratio: 2,
      can_submit: true,
      blocking_reason: null,
    },
    broker_result: null,
    order_id: null,
    terminal_reason: null,
    ...overrides,
  };
}

test("PREVIEWED positive-size intent is submittable only when paper gate is ready", () => {
  const ready = manualIntentCapability(intent(), true);
  assert.equal(ready.canSubmit, true);
  assert.deepEqual(ready.reasons, []);

  const blocked = manualIntentCapability(intent(), false);
  assert.equal(blocked.canSubmit, false);
  assert.ok(blocked.reasons.includes("paper execution gate is not ready"));
});

test("zero server-sized quantity blocks submit", () => {
  const base = intent();
  const result = manualIntentCapability(
    intent({
      status: "BLOCKED",
      preview: {
        ...base.preview,
        final_quantity: 0,
        final_dollar_risk: 0,
        can_submit: false,
        blocking_reason: "Risk budget cannot support one MES unit",
      },
      terminal_reason: "Risk budget cannot support one MES unit",
    }),
    true,
  );
  assert.equal(result.canSubmit, false);
  assert.ok(result.reasons.some((reason) => reason.includes("BLOCKED")));
  assert.ok(result.reasons.some((reason) => reason.includes("zero")));
});

test("SUBMITTING is explicitly reconciliation-required and never retryable", () => {
  const result = manualIntentCapability(intent({ status: "SUBMITTING" }), true);
  assert.equal(result.canSubmit, false);
  assert.equal(result.requiresReconciliation, true);
  assert.ok(result.reasons.includes("intent status is SUBMITTING"));
});

test("SUBMITTED is terminal and cannot be submitted again from the UI", () => {
  const result = manualIntentCapability(
    intent({ status: "SUBMITTED", order_id: "entry-1" }),
    true,
  );
  assert.equal(result.canSubmit, false);
  assert.equal(result.requiresReconciliation, false);
});

test("BLOCKED and EXPIRED intents cannot be submitted", () => {
  for (const status of ["BLOCKED", "EXPIRED"] as const) {
    const result = manualIntentCapability(intent({ status }), true);
    assert.equal(result.canSubmit, false);
    assert.ok(result.reasons.includes(`intent status is ${status}`));
  }
});

test("missing preview fails closed", () => {
  const result = manualIntentCapability(null, true);
  assert.equal(result.canSubmit, false);
  assert.deepEqual(result.reasons, ["preview required"]);
});
