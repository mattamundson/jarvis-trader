/**
 * P5.1 — real unit tests for the flagship command-center's honesty-critical
 * pure helpers (extracted to app/command-center/format-helpers.ts so they can
 * be loaded outside the page's JSX). `suspectPrice` is the correctness-critical
 * one: it's the honesty gate (folded from /trust, P2.1) that flags a corrupted
 * futures price (the 2026-06-12 MES@100.5 STC-leak class) instead of silently
 * rendering it as real. Same Node built-in test-runner convention as
 * tests/position-sizing.test.ts (no Jest/Vitest, no RTL/jsdom needed since
 * these are plain functions, not rendered components).
 *
 * Run via: node --test tests/command-center-helpers.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { fmtPct, pnlColor, suspectPrice } from "../app/command-center/format-helpers.ts";

test("suspectPrice flags a corrupted MES price below its floor", () => {
  assert.equal(suspectPrice("MES", 100.5), true);
});

test("suspectPrice does not flag a real MES price above its floor", () => {
  assert.equal(suspectPrice("MES", 5321.25), false);
});

test("suspectPrice is case-insensitive on symbol", () => {
  assert.equal(suspectPrice("mgc", 100), true);
});

test("suspectPrice never flags a non-positive price (no data yet, not corrupted)", () => {
  assert.equal(suspectPrice("MES", 0), false);
  assert.equal(suspectPrice("MES", -5), false);
});

test("suspectPrice returns false for a symbol with no known floor", () => {
  assert.equal(suspectPrice("XYZ", 0.01), false);
});

test("fmtPct signs positive/negative/zero and rounds to the given precision", () => {
  assert.equal(fmtPct(1.006, 2), "+1.01%");
  assert.equal(fmtPct(-2.5), "-2.50%");
  assert.equal(fmtPct(0), "+0.00%");
  assert.equal(fmtPct(null), "—");
});

test("pnlColor maps sign to the correct Tailwind class", () => {
  assert.equal(pnlColor(150), "text-green-400");
  assert.equal(pnlColor(-1), "text-red-400");
  assert.equal(pnlColor(0), "text-gray-300");
  assert.equal(pnlColor(undefined), "text-gray-400");
});
