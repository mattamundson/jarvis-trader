/**
 * P5.1 — real unit test for the shared ATR position-sizing formula.
 *
 * `lib/position-sizing.ts` (P3.4) replaced two independently-drifting
 * hardcoded implementations; unlike this project's tsc-only "compile-time
 * test" convention (tests/*.test.tsx, tests/MasterApiCircuitBreaker.test.ts
 * — type-shape checks that never execute the function body), position-sizing
 * is a correctness-critical pure function, so this test actually RUNS it and
 * asserts real numeric outputs via Node's built-in test runner (zero new
 * dependencies — Node 22.6+ strips TS types natively; no Jest/Vitest needed).
 *
 * Run via: node --test tests/position-sizing.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { calcAtrPositionSize } from "../lib/position-sizing.ts";

const MES_BASE = {
  atr: 10,
  accountValue: 10_000,
  riskPct: 0.01,
  atrStopMultiplier: 1,
  atrTargetMultiplier: 2,
  tickValue: 1.25,
  ticksPerPoint: 4,
};

test("computes ticks/dollars/contracts for a known MES-style input", () => {
  const r = calcAtrPositionSize({ ...MES_BASE, maxContracts: 5 });
  assert.equal(r.atrTicks, 40);
  assert.equal(r.stopTicks, 40);
  assert.equal(r.targetTicks, 80);
  assert.equal(r.stopDollar, 50);
  assert.equal(r.targetDollar, 100);
  assert.equal(r.riskPerContract, 50);
  assert.equal(r.riskPerTrade, 100);
  assert.equal(r.computedContracts, 2);
  assert.equal(r.effectiveContracts, 2);
});

test("caps effectiveContracts at maxContracts without altering computedContracts", () => {
  const r = calcAtrPositionSize({ ...MES_BASE, maxContracts: 1 });
  assert.equal(r.computedContracts, 2);
  assert.equal(r.effectiveContracts, 1);
});

test("guards the division: zero ATR yields zero contracts, not NaN/Infinity", () => {
  const r = calcAtrPositionSize({ ...MES_BASE, atr: 0, maxContracts: 5 });
  assert.equal(r.riskPerContract, 0);
  assert.equal(r.computedContracts, 0);
  assert.equal(r.effectiveContracts, 0);
});
