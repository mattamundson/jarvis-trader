// Regression: PREFERRED_BASELINE_SYMBOL_SUBSTRINGS must track the currently-
// approved pair, not a separately-drifting literal.
//
// WHY: this constant used to be its own hardcoded ["MCL", "MNQ"] array --
// MCL/MNQ are DO_NOT_TRADE_SYMBOLS (halted since the 2026-05-24 instrument
// switch) -- self-contradicting DEFAULT_BRIEFING_SYMBOLS (["MES", "MGC"])
// defined two lines above it in the same file. That made
// pickApprovedBacktestBaseline() in scorecardBaseline.ts silently prefer a
// halted instrument's backtest over the actually-approved pair's whenever
// both were present in the results pool. Deriving PREFERRED_BASELINE_SYMBOL_
// SUBSTRINGS from DEFAULT_BRIEFING_SYMBOLS closes that drift permanently;
// this test locks the derived behavior so it can't silently regress.
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

test("matchesPreferredBaseline matches the approved pair (MES/MGC)", () => {
  assert.equal(matchesPreferredBaseline("MES mes_1h_backtest.json"), true);
  assert.equal(matchesPreferredBaseline("MGC mgc_1h_backtest.json"), true);
});

test("matchesPreferredBaseline no longer matches the halted pair (MCL/MNQ)", () => {
  assert.equal(matchesPreferredBaseline("MCL mcl_1h_backtest.json"), false);
  assert.equal(matchesPreferredBaseline("MNQ mnq_1h_backtest.json"), false);
});
