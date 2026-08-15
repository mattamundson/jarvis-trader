// Regression: PREFERRED_BASELINE_SYMBOL_SUBSTRINGS must track the currently-
// approved symbol(s), not a separately-drifting literal.
//
// WHY: this constant used to be its own hardcoded ["MCL", "MNQ"] array --
// MCL/MNQ are DO_NOT_TRADE_SYMBOLS (halted since the 2026-05-24 instrument
// switch) -- self-contradicting DEFAULT_BRIEFING_SYMBOLS defined two lines
// above it in the same file. That made pickApprovedBacktestBaseline() in
// scorecardBaseline.ts silently prefer a halted instrument's backtest over
// the actually-approved symbol's whenever both were present in the results
// pool. Deriving PREFERRED_BASELINE_SYMBOL_SUBSTRINGS from
// DEFAULT_BRIEFING_SYMBOLS closes that drift permanently; this test locks
// the derived behavior so it can't silently regress.
//
// DEFAULT_BRIEFING_SYMBOLS was further reduced from ["MES", "MGC"] to
// ["MES"] on 2026-08-01 (PR #552) once MGC itself joined DO_NOT_TRADE_SYMBOLS
// -- see the docstring in lib/approvedSymbols.ts. MGC is asserted alongside
// MCL/MNQ below for the same halted-symbol reason.
//
// Run: cd dashboard && pnpm run test:unit

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_BRIEFING_SYMBOLS,
  PREFERRED_BASELINE_SYMBOL_SUBSTRINGS,
  matchesPreferredBaseline,
} from "../lib/approvedSymbols.ts";

test("PREFERRED_BASELINE_SYMBOL_SUBSTRINGS equals DEFAULT_BRIEFING_SYMBOLS", () => {
  assert.deepEqual([...PREFERRED_BASELINE_SYMBOL_SUBSTRINGS], [...DEFAULT_BRIEFING_SYMBOLS]);
});

test("matchesPreferredBaseline matches the approved symbol (MES)", () => {
  assert.equal(matchesPreferredBaseline("MES mes_1h_backtest.json"), true);
});

test("matchesPreferredBaseline no longer matches the halted symbols (MCL/MNQ/MGC)", () => {
  assert.equal(matchesPreferredBaseline("MCL mcl_1h_backtest.json"), false);
  assert.equal(matchesPreferredBaseline("MNQ mnq_1h_backtest.json"), false);
  assert.equal(matchesPreferredBaseline("MGC mgc_1h_backtest.json"), false);
});
