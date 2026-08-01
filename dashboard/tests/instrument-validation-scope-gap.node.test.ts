// Regression test for D2-03-v2 (2026-07-24 dashboard-integrity audit,
// follow-up to D2-03/scorecard-baseline-active-pair.node.test.ts).
//
// D2-03's lib-level fix (PREFERRED_BASELINE_SYMBOL_SUBSTRINGS derived from
// DEFAULT_BRIEFING_SYMBOLS) never propagated to five components that had
// their OWN independent hardcoded MCL/MNQ text/logic:
//   - BacktestVsPaperWidget.tsx ("MCL/MNQ preferred" label)
//   - app/validation/page.tsx ("No MCL/MNQ baseline JSON" etc. + a
//     SimulateTradePanel `SYMBOLS`/default-selector defaulting to "MCL")
//   - app/scorecard/page.tsx ("MCL/MNQ preferred" labels)
//   - components/InstrumentValidationScorecard.tsx (a *factual* bug: it
//     hardcoded MCL/MNQ as APPROVED-and-trading with static WFE 0.82/0.57,
//     and MES as "Revalidating" — the exact opposite of engine reality)
//   - PaperApprovedValidationWidget.tsx ("Paper validation — MCL & MNQ")
//
// PRB-36 UPDATE (2026-07-30): InstrumentValidationScorecard.tsx and its
// lib/instrumentValidationRows.ts row-builder (along with approvedSymbols.ts's
// INSTRUMENT_STATUS override table they depended on) turned out to have their
// own, worse bug -- INSTRUMENT_STATUS hardcoded MES/MGC WFE to 1.00 regardless
// of live data and fabricated an "APPROVED" fallback for any symbol the live
// gates endpoint didn't return a row for. Both files and INSTRUMENT_STATUS
// were retired in favor of the live-sourced lib/tradingEligibility.ts pattern
// (see tests/tradingEligibility.node.test.ts for that transform's coverage).
// The three tests that locked buildInstrumentRow/buildDefaultInstrumentRows/
// INSTRUMENT_STATUS were removed here since their target no longer exists;
// the remaining approvedSymbols.ts export tests below are still valid and
// were left in place.
//
// Run: cd dashboard && pnpm run test:unit

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_BRIEFING_SYMBOLS,
  HALTED_SYMBOLS,
  ALL_TRACKED_SYMBOLS,
  PREFERRED_BASELINE_LABEL,
} from "../lib/approvedSymbols.ts";

// ── approvedSymbols.ts additions ────────────────────────────────────────────

test("PREFERRED_BASELINE_LABEL renders the active pair, not the halted one", () => {
  assert.equal(PREFERRED_BASELINE_LABEL, "MES/MGC");
});

test("HALTED_SYMBOLS never overlaps DEFAULT_BRIEFING_SYMBOLS", () => {
  for (const sym of HALTED_SYMBOLS) {
    assert.ok(
      !(DEFAULT_BRIEFING_SYMBOLS as readonly string[]).includes(sym),
      `HALTED_SYMBOLS must not include an actively-traded symbol, found "${sym}"`
    );
  }
  // Full engine-parity halt list (backtest/signals.py::DO_NOT_TRADE_SYMBOLS) --
  // includes M2K, which this component set has no dashboard view for (see
  // ALL_TRACKED_SYMBOLS below). Locked in parity with the engine by
  // symbol-status-halt-parity.node.test.ts.
  assert.deepEqual([...HALTED_SYMBOLS].sort(), ["M2K", "MCL", "MNQ"]);
});

test("ALL_TRACKED_SYMBOLS is the active pair followed by the halted pair, no duplicates", () => {
  assert.deepEqual([...ALL_TRACKED_SYMBOLS], ["MES", "MGC", "MCL", "MNQ"]);
  assert.equal(new Set(ALL_TRACKED_SYMBOLS).size, ALL_TRACKED_SYMBOLS.length);
});
