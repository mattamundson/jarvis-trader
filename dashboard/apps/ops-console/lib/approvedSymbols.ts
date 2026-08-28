/**
 * Default symbols for dashboard/Discord briefing widgets (T3-23, 2026-07-09).
 * Canonical active paper-trading symbol per the 2026-08-27 MES-only scope —
 * see jarvis-trader/CLAUDE.md "Active Instruments". Mirrors
 * `engine/backtest/signals.py::DEFAULT_BRIEFING_SYMBOLS` (TS/Python can't
 * share a literal source, so this is the dashboard-side twin) — update both
 * together if the active set ever changes again.
 */
export const DEFAULT_BRIEFING_SYMBOLS = ["MES"] as const;

/**
 * Symbols currently blocked from trading, mirroring the engine's live
 * blocklist (engine/backtest/signals.py::DO_NOT_TRADE_SYMBOLS). TS/Python
 * can't share a literal source, so this is the dashboard-side twin — update
 * both together if the engine blocklist ever changes. See
 * dashboard/tests/symbol-status-halt-parity.node.test.ts for the regression
 * guard (D2-02: inverted APPROVED/HALTED badges).
 */
export const HALTED_SYMBOLS = ["MGC", "MCL", "MNQ", "M2K"] as const;

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
