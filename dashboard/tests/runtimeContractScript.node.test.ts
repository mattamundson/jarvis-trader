import { test } from "node:test";
import assert from "node:assert/strict";
import {
  dashboardHeaders,
  validateBrokerContract,
  validateHealthContract,
  validateRuntimeSnapshotContract,
  validateSafetyStatusContract,
  validateTradingStatusContract,
} from "../scripts/check-runtime-contract.mjs";

test("health contract accepts the live shape", () => {
  assert.deepEqual(
    validateHealthContract({
      status: "ok",
      live_trading: false,
      kill_switch_active: true,
      ibkr_connected: false,
    }),
    [],
  );
});

test("broker contract requires schwab policy discrepancy detail", () => {
  assert.deepEqual(
    validateBrokerContract({
      schwab: { status: "disabled_by_policy" },
      reconciliation: {
        discrepancies: [
          { broker_family: "schwab", type: "paper_unverified", detail: "SCHWAB_READY=false" },
        ],
      },
    }),
    [],
  );

  const errors = validateBrokerContract({
    schwab: { status: "disabled_by_policy" },
    reconciliation: { discrepancies: [] },
  });
  assert.ok(errors.some((error) => error.includes("paper_unverified")));
});

test("dashboardHeaders adds Basic auth only when requested", () => {
  const prior = process.env.DASHBOARD_BASIC_AUTH;
  try {
    delete process.env.DASHBOARD_BASIC_AUTH;
    assert.deepEqual(dashboardHeaders(), {});
    process.env.DASHBOARD_BASIC_AUTH = "user:pass";
    assert.deepEqual(dashboardHeaders(), {
      Authorization: `Basic ${Buffer.from("user:pass").toString("base64")}`,
    });
  } finally {
    if (prior == null) {
      delete process.env.DASHBOARD_BASIC_AUTH;
    } else {
      process.env.DASHBOARD_BASIC_AUTH = prior;
    }
  }
});

test("safety status contract requires the fields RiskSafetyPanel reads", () => {
  assert.deepEqual(
    validateSafetyStatusContract({
      kill_switch_active: false,
      kill_switch_reason: null,
      daily_pnl: -120,
      daily_pnl_pct: -0.01,
      daily_limit_pct: 0.02,
      daily_limit_breached: false,
      drawdown_pct: -0.03,
      drawdown_limit_pct: 0.1,
      drawdown_breached: false,
      portfolio_equity: 25000,
      current_balance: 25100,
    }),
    [],
  );

  const errors = validateSafetyStatusContract({ kill_switch_active: false });
  assert.ok(errors.includes("portfolio_equity must be finite number"));
  assert.ok(errors.includes("drawdown_breached must be boolean"));
});

test("trading status contract requires summary counts and per-symbol booleans", () => {
  assert.deepEqual(
    validateTradingStatusContract({
      summary: { total: 1, tradeable: 0, enabled: 1, disagreements: 1 },
      symbols: [
        {
          symbol: "MES",
          enabled: true,
          authorized: true,
          tradeable: false,
          config_agrees: false,
          disagreements: ["example"],
        },
      ],
    }),
    [],
  );

  const errors = validateTradingStatusContract({
    summary: { total: 1, tradeable: 0, enabled: 1, disagreements: 1 },
    symbols: [{ symbol: "MES", enabled: true }],
  });
  assert.ok(errors.some((error) => error.includes("authorized must be boolean")));
  assert.ok(errors.some((error) => error.includes("disagreements must be array")));
});

test("runtime snapshot contract requires contract + source_integrity sections", () => {
  assert.deepEqual(
    validateRuntimeSnapshotContract({
      captured_at_utc: "2026-09-03T05:12:07+00:00",
      contract: { required_sections_present: true, missing_sections: [] },
      source_integrity: {
        overall: "fail",
        checks: [{ label: "Canonical deploy", status: "fail", finding_count: 3 }],
      },
    }),
    [],
  );

  const errors = validateRuntimeSnapshotContract({
    contract: { required_sections_present: false, missing_sections: ["api.eligibility"] },
  });
  assert.ok(errors.some((error) => error.includes("missing required sections")));
  assert.ok(errors.some((error) => error.includes("source_integrity section is missing")));
});
