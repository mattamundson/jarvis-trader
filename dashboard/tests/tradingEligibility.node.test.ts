// Trading Eligibility panel — pure transform tests (PRB-25).
//
// WHY: docs/CURRENT_STATE.md's static "Approved Instruments" table drifted
// from live gate reality repeatedly (dated June 18, showed MES/MGC
// "APPROVED — paper active" while the live endpoint reported
// overall_pass=false for both). These tests lock the contract that
// eligibilityRows() reads ONLY from the engine's live response — no
// hardcoded symbol list, no "always APPROVED" override — so the dashboard
// side of this feature structurally cannot repeat that staleness failure.
//
// Run: cd dashboard && pnpm run test:unit

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  eligibilityRows,
  eligibleCount,
  formatGateValue,
  trackedSymbols,
} from "../lib/tradingEligibility.ts";
import type { ApprovedPaperGatesResponse } from "../lib/api.ts";

function makeResponse(
  instruments: ApprovedPaperGatesResponse["instruments"]
): ApprovedPaperGatesResponse {
  return {
    status: "ok",
    thresholds: { profit_factor: 1.5, sharpe_ratio: 1.0 },
    instruments,
    note: "test note",
  };
}

test("eligibilityRows returns [] when data is undefined (offline/loading, never fabricates)", () => {
  assert.deepEqual(eligibilityRows(undefined), []);
});

test("eligibilityRows returns [] when instruments is missing from the payload", () => {
  const data = { status: "ok", thresholds: {}, note: "" } as ApprovedPaperGatesResponse;
  assert.deepEqual(eligibilityRows(data), []);
});

test("a passing instrument maps to ELIGIBLE / bull tone", () => {
  const data = makeResponse([
    {
      symbol: "MES",
      trade_count: 12,
      days_with_trades: 5,
      overall_pass: true,
      gates: [
        { name: "profit_factor", current: 2.1, target: 1.5, passes: true, unit: "" },
      ],
    },
  ]);
  const [row] = eligibilityRows(data);
  assert.equal(row.symbol, "MES");
  assert.equal(row.overallPass, true);
  assert.equal(row.tone, "bull");
  assert.equal(row.label, "ELIGIBLE");
  assert.deepEqual(row.failingGateNames, []);
});

test("a failing instrument maps to NOT ELIGIBLE / bear tone, regardless of symbol", () => {
  // Deliberately picks MGC and MES — the exact pair CURRENT_STATE.md's stale
  // table hardcoded as "APPROVED — paper active" — to lock that this
  // transform has no memory of that claim and reports live reality only.
  const data = makeResponse([
    {
      symbol: "MGC",
      trade_count: 40,
      days_with_trades: 20,
      overall_pass: false,
      gates: [
        { name: "profit_factor", current: 0.8, target: 1.5, passes: false, unit: "" },
        { name: "max_drawdown", current: 18.27, target: 10, passes: false, unit: "%" },
      ],
    },
    {
      symbol: "MES",
      trade_count: 30,
      days_with_trades: 15,
      overall_pass: false,
      gates: [{ name: "sharpe_ratio", current: 0.4, target: 1.0, passes: false, unit: "" }],
    },
  ]);
  const rows = eligibilityRows(data);
  assert.equal(rows.length, 2);
  for (const row of rows) {
    assert.equal(row.overallPass, false);
    assert.equal(row.tone, "bear");
    assert.equal(row.label, "NOT ELIGIBLE");
    assert.ok(row.failingGateNames.length > 0);
  }
  const mgc = rows.find((r) => r.symbol === "MGC")!;
  assert.deepEqual(mgc.failingGateNames, ["profit_factor", "max_drawdown"]);
});

test("eligibleCount counts only overall_pass=true rows", () => {
  const rows = eligibilityRows(
    makeResponse([
      { symbol: "A", trade_count: 1, days_with_trades: 1, overall_pass: true, gates: [] },
      { symbol: "B", trade_count: 1, days_with_trades: 1, overall_pass: false, gates: [] },
      { symbol: "C", trade_count: 1, days_with_trades: 1, overall_pass: true, gates: [] },
    ])
  );
  assert.equal(eligibleCount(rows), 2);
});

test("trackedSymbols reflects exactly what the engine returned, nothing added or assumed", () => {
  const data = makeResponse([
    { symbol: "MCL", trade_count: 0, days_with_trades: 0, overall_pass: false, gates: [] },
    { symbol: "MNQ", trade_count: 0, days_with_trades: 0, overall_pass: false, gates: [] },
  ]);
  assert.deepEqual(trackedSymbols(data), ["MCL", "MNQ"]);
  // A symbol absent from the live response (e.g. MGC, if the engine's
  // APPROVED_PAPER_SYMBOLS doesn't include it) must never silently appear.
  assert.ok(!trackedSymbols(data).includes("MGC"));
});

test("formatGateValue renders an integer without decimals plus the unit", () => {
  assert.equal(formatGateValue(10, "days"), "10days");
  assert.equal(formatGateValue(0, ""), "0");
});

test("formatGateValue renders a fractional value to 2 decimals", () => {
  assert.equal(formatGateValue(2.567, ""), "2.57");
  assert.equal(formatGateValue(43.75, "%"), "43.75%");
});

test("formatGateValue never fabricates a number for non-finite input", () => {
  assert.equal(formatGateValue(NaN, ""), "—");
  assert.equal(formatGateValue(Infinity, "%"), "—");
});
