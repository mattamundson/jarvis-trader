// Regression test for D2-03 (2026-07-24 dashboard-integrity audit): the
// backtest-vs-paper scorecard baseline was pinned to the HALTED MCL/MNQ pair
// (engine/backtest/signals.py DO_NOT_TRADE_SYMBOLS) while paper trading
// actually runs the active MES/MGC pair. That meant /validation (the go/no-go
// readiness page), /scorecard, and BacktestVsPaperWidget.tsx were all
// comparing live performance against instruments the engine refuses to trade.
//
// Fix: PREFERRED_BASELINE_SYMBOL_SUBSTRINGS is now derived from
// DEFAULT_BRIEFING_SYMBOLS (["MES","MGC"]) instead of a stale ["MCL","MNQ"]
// literal, so the baseline always tracks the actively-traded pair.
//
// Run: cd dashboard && pnpm run test:unit

import { test } from "node:test";
import assert from "node:assert/strict";
import { pickApprovedBacktestBaseline, type BacktestBaselineRow } from "../lib/scorecardBaseline.ts";
import {
  PREFERRED_BASELINE_SYMBOL_SUBSTRINGS,
  DEFAULT_BRIEFING_SYMBOLS,
  matchesPreferredBaseline,
} from "../lib/approvedSymbols.ts";

// ── Case 1: reproduce — must fail pre-fix, pass post-fix ───────────────────
test("pickApprovedBacktestBaseline prefers the active MES/MGC pair over the halted MCL/MNQ pair", () => {
  const rows: BacktestBaselineRow[] = [
    {
      symbol: "MCL",
      _filename: "composite_MCL_1h.json",
      profit_factor: 1.5,
      full_metrics: { profit_factor: 1.5 },
    },
    {
      symbol: "MNQ",
      _filename: "composite_MNQ_1h.json",
      profit_factor: 1.6,
      full_metrics: { profit_factor: 1.6 },
    },
    {
      symbol: "MES",
      _filename: "composite_MES_1h.json",
      profit_factor: 1.4,
      full_metrics: { profit_factor: 1.4 },
    },
    {
      symbol: "MGC",
      _filename: "composite_MGC_1h.json",
      profit_factor: 1.3,
      full_metrics: { profit_factor: 1.3 },
    },
  ];

  const baseline = pickApprovedBacktestBaseline(rows);
  assert.ok(baseline, "expected a baseline to be picked");
  assert.ok(
    baseline!.label.startsWith("MES") || baseline!.label.startsWith("MGC"),
    `expected baseline label to start with MES or MGC (active pair), got "${baseline!.label}"`,
  );
  assert.ok(
    !baseline!.label.startsWith("MCL") && !baseline!.label.startsWith("MNQ"),
    `baseline must not be drawn from the halted MCL/MNQ pair, got "${baseline!.label}"`,
  );
});

// ── Case 2: pin both directions ─────────────────────────────────────────────
test("matchesPreferredBaseline is true for the active pair, false for the halted pair", () => {
  assert.equal(matchesPreferredBaseline("MES composite_MES_1h.json"), true);
  assert.equal(matchesPreferredBaseline("MGC composite_MGC_1h.json"), true);
  assert.equal(matchesPreferredBaseline("MCL composite_MCL_1h.json"), false);
  assert.equal(matchesPreferredBaseline("MNQ composite_MNQ_1h.json"), false);
});

// ── Case 3: cross-source disjointness ───────────────────────────────────────
test("PREFERRED_BASELINE_SYMBOL_SUBSTRINGS never overlaps engine DO_NOT_TRADE_SYMBOLS and tracks DEFAULT_BRIEFING_SYMBOLS", () => {
  // Mirrors engine/backtest/signals.py DO_NOT_TRADE_SYMBOLS (checked-in fixture,
  // not a live import — TS/Python can't share a literal source; see
  // approvedSymbols.ts's DEFAULT_BRIEFING_SYMBOLS docstring).
  const ENGINE_DO_NOT_TRADE = ["MCL", "MNQ", "M2K"];

  for (const sym of PREFERRED_BASELINE_SYMBOL_SUBSTRINGS) {
    assert.ok(
      !ENGINE_DO_NOT_TRADE.includes(sym),
      `PREFERRED_BASELINE_SYMBOL_SUBSTRINGS must not contain a halted symbol, found "${sym}"`,
    );
  }

  assert.deepEqual(
    [...PREFERRED_BASELINE_SYMBOL_SUBSTRINGS].sort(),
    [...DEFAULT_BRIEFING_SYMBOLS].sort(),
    "PREFERRED_BASELINE_SYMBOL_SUBSTRINGS must deep-equal DEFAULT_BRIEFING_SYMBOLS (sorted)",
  );
});
