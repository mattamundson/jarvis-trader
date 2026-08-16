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
// PRB-36 NOTE (2026-07-30): this file's contract (HALTED_SYMBOLS parity +
// symbolTradeStatus()) is orthogonal to the bug PRB-36 fixed and needed no
// expectation changes here. The retired bug lived in a *different* export --
// approvedSymbols.ts's INSTRUMENT_STATUS table (a static per-symbol WFE +
// status override with a fabricated "APPROVED" fallback for symbols the live
// gates endpoint didn't return), consumed only by the now-deleted
// InstrumentValidationScorecard.tsx / lib/instrumentValidationRows.ts (see
// tests/instrument-validation-scope-gap.node.test.ts, trimmed accordingly).
// HALTED_SYMBOLS and symbolTradeStatus() below are still hand-mirrored,
// still-hardcoded-by-design (the engine's DO_NOT_TRADE_SYMBOLS has no TS-side
// live source), and still correct -- so this test's assertions are unchanged.
//
// Run: cd dashboard && pnpm run test:unit
//   (node --test --experimental-strip-types "tests/**/*.node.test.ts")

import { test } from "node:test";
import assert from "node:assert/strict";
import { HALTED_SYMBOLS, symbolTradeStatus } from "../lib/approvedSymbols.ts";

// Checked-in fixture mirroring engine/backtest/signals.py::DO_NOT_TRADE_SYMBOLS
// (~line 122) as of 2026-08-01 (PR #552 added MGC). Update alongside the
// engine source if it changes.
const ENGINE_DO_NOT_TRADE = ["MCL", "MNQ", "M2K", "MGC"];

test("HALTED_SYMBOLS stays in parity with the engine's DO_NOT_TRADE_SYMBOLS fixture", () => {
  assert.deepEqual([...HALTED_SYMBOLS].sort(), [...ENGINE_DO_NOT_TRADE].sort());
});

test("symbolTradeStatus marks halted symbols HALTED", () => {
  assert.equal(symbolTradeStatus("MCL"), "HALTED");
  assert.equal(symbolTradeStatus("MNQ"), "HALTED");
  assert.equal(symbolTradeStatus("MGC"), "HALTED");
});

test("symbolTradeStatus marks the active trading symbol APPROVED", () => {
  assert.equal(symbolTradeStatus("MES"), "APPROVED");
});
