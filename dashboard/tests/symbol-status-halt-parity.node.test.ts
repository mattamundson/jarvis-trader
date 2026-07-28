// Regression test for D2-02: inverted APPROVED/HALTED symbol-status badges.
//
// WHY: dashboard/lib/approvedSymbols.ts::HALTED_SYMBOLS mirrors the engine's
// live halt list (engine/backtest/signals.py::DO_NOT_TRADE_SYMBOLS) by hand
// since TS/Python can't share a literal source. This test locks the mirrored
// list to a checked-in fixture of the engine's real value and locks
// symbolTradeStatus()'s APPROVED/HALTED classification, so a future edit to
// one side without the other becomes a failing test instead of a live badge
// showing MCL/MNQ green-APPROVED and MGC red-HALTED (exactly backwards).
//
// Run: cd dashboard && pnpm run test:unit
//   (node --test --experimental-strip-types "tests/**/*.node.test.ts")

import { test } from "node:test";
import assert from "node:assert/strict";
import { HALTED_SYMBOLS, symbolTradeStatus } from "../lib/approvedSymbols.ts";

// Checked-in fixture mirroring engine/backtest/signals.py::DO_NOT_TRADE_SYMBOLS
// (~line 113) as of 2026-07-24. Update alongside the engine source if it changes.
const ENGINE_DO_NOT_TRADE = ["MCL", "MNQ", "M2K"];

test("HALTED_SYMBOLS stays in parity with the engine's DO_NOT_TRADE_SYMBOLS fixture", () => {
  assert.deepEqual([...HALTED_SYMBOLS].sort(), [...ENGINE_DO_NOT_TRADE].sort());
});

test("symbolTradeStatus marks halted symbols HALTED", () => {
  assert.equal(symbolTradeStatus("MCL"), "HALTED");
  assert.equal(symbolTradeStatus("MNQ"), "HALTED");
});

test("symbolTradeStatus marks the active trading pair APPROVED", () => {
  assert.equal(symbolTradeStatus("MES"), "APPROVED");
  assert.equal(symbolTradeStatus("MGC"), "APPROVED");
});
