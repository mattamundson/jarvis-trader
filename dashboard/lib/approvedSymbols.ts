<<<<<<< HEAD
=======
/**
 * Default symbol(s) for dashboard/Discord briefing widgets (T3-23,
 * 2026-07-09; reduced to MES-only 2026-08-01 after MGC joined the engine's
 * DO_NOT_TRADE_SYMBOLS, PR #552). Canonical active paper-trading symbol(s)
 * per jarvis-trader/CLAUDE.md "Active Instruments". Mirrors
 * `engine/backtest/signals.py::DEFAULT_BRIEFING_SYMBOLS` (TS/Python can't
 * share a literal source, so this is the dashboard-side twin) — update both
 * together if the active set ever changes again.
 */
export const DEFAULT_BRIEFING_SYMBOLS = ["MES"] as const;

/**
 * Substrings matched against symbol + _filename when picking a dashboard
 * backtest baseline. Derived from DEFAULT_BRIEFING_SYMBOLS so the baseline
 * always tracks the ACTIVELY-TRADED pair. Was [MCL,MNQ] pre-fix — a stale
 * literal left over from an earlier migration.
 */
export const PREFERRED_BASELINE_SYMBOL_SUBSTRINGS = DEFAULT_BRIEFING_SYMBOLS;

export function matchesPreferredBaseline(symbolAndFilename: string): boolean {
  const u = symbolAndFilename.toUpperCase();
  return PREFERRED_BASELINE_SYMBOL_SUBSTRINGS.some((s) => u.includes(s));
}

>>>>>>> origin/master
/**
 * "MES" — human-readable label for the preferred baseline symbol(s), for UI
 * copy that used to hardcode the stale "MCL/MNQ preferred" string (D2-03-v2,
 * 2026-07-24 audit). Derived so the label can never drift from
 * DEFAULT_BRIEFING_SYMBOLS again.
 */
<<<<<<< HEAD
export const DEFAULT_BRIEFING_SYMBOLS = ["MES", "MGC"] as const;

/**
 * Symbols currently blocked from trading, mirroring the engine's live
 * blocklist (engine/backtest/signals.py::DO_NOT_TRADE_SYMBOLS). TS/Python
 * can't share a literal source, so this is the dashboard-side twin — update
 * both together if the engine blocklist ever changes. See
 * dashboard/tests/symbol-status-halt-parity.node.test.ts for the regression
 * guard (D2-02: inverted APPROVED/HALTED badges).
 */
export const HALTED_SYMBOLS = ["MCL", "MNQ", "M2K"] as const;

export function symbolTradeStatus(symbol: string): "APPROVED" | "HALTED" {
  return (HALTED_SYMBOLS as readonly string[]).includes(symbol) ? "HALTED" : "APPROVED";
}

/**
 * Substrings matched against `symbol` + `_filename` when picking a dashboard
 * backtest baseline. Derived from DEFAULT_BRIEFING_SYMBOLS (not a separate
 * literal) so it can't drift the way it did before -- this used to be its own
 * hardcoded ["MCL", "MNQ"] array, self-contradicting the pair defined two
 * lines above in the same file, and silently making pickApprovedBacktestBaseline()
 * prefer a halted instrument's backtest over the actually-approved pair's.
 */
export const PREFERRED_BASELINE_SYMBOL_SUBSTRINGS: readonly string[] = DEFAULT_BRIEFING_SYMBOLS;

export function matchesPreferredBaseline(symbolAndFilename: string): boolean {
  const u = symbolAndFilename.toUpperCase();
  return PREFERRED_BASELINE_SYMBOL_SUBSTRINGS.some((s) => u.includes(s));
}
=======
export const PREFERRED_BASELINE_LABEL = DEFAULT_BRIEFING_SYMBOLS.join("/");

/** Mirrors engine/backtest/signals.py::DO_NOT_TRADE_SYMBOLS (TS/Python cannot share a literal) -- update both together. Locked to this exact value by tests/symbol-status-halt-parity.node.test.ts. */
export const HALTED_SYMBOLS = ["MCL", "MNQ", "M2K", "MGC"] as const;

export function symbolTradeStatus(sym: string): "APPROVED" | "HALTED" {
  return (HALTED_SYMBOLS as readonly string[]).includes(sym.toUpperCase()) ? "HALTED" : "APPROVED";
}

/**
 * The subset of HALTED_SYMBOLS this component set's INSTRUMENT_STATUS table
 * actually tracks. M2K has no dashboard view in this component set (see
 * HALTED_SYMBOLS above for the full authoritative engine halt list) so it's
 * intentionally excluded here — add it if a consumer ever needs it. MGC
 * added 2026-08-01 (moved out of DEFAULT_BRIEFING_SYMBOLS when it joined
 * DO_NOT_TRADE_SYMBOLS, PR #552) so it stays visible to symbol pickers with
 * a correct HALTED status instead of silently disappearing from them.
 */
const DASHBOARD_HALTED_SYMBOLS = ["MCL", "MNQ", "MGC"] as const;

/** Every symbol this component set knows about, active symbol(s) first. */
export const ALL_TRACKED_SYMBOLS = [
  ...DEFAULT_BRIEFING_SYMBOLS,
  ...DASHBOARD_HALTED_SYMBOLS,
] as const;

export type TrackedSymbol = (typeof ALL_TRACKED_SYMBOLS)[number];

// NOTE (PRB-36, 2026-07-30): INSTRUMENT_STATUS used to live here — a static
// per-symbol WFE + approval-status override table (MES/MGC hardcoded 1.00
// WFE/APPROVED, MCL/MNQ hardcoded 0.00/HALTED, with a fabricated "APPROVED"
// fallback for any symbol the live gates endpoint didn't return a row for).
// It powered InstrumentValidationScorecard.tsx / instrumentValidationRows.ts,
// both retired by this fix in favor of the live-sourced pattern in
// lib/tradingEligibility.ts (GET /paper/validation/approved-paper-gates,
// zero hardcoded symbol table, no fail-open default) -- see
// app/trading-eligibility/page.tsx and /validation section 1B.
>>>>>>> origin/master
