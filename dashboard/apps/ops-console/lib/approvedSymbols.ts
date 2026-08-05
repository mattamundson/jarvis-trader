/** Substrings matched against `symbol` + `_filename` when picking a dashboard backtest baseline. */
export const PREFERRED_BASELINE_SYMBOL_SUBSTRINGS = ["MCL", "MNQ"] as const;

export function matchesPreferredBaseline(symbolAndFilename: string): boolean {
  const u = symbolAndFilename.toUpperCase();
  return PREFERRED_BASELINE_SYMBOL_SUBSTRINGS.some((s) => u.includes(s));
}

/**
 * Default symbols for dashboard/Discord briefing widgets (T3-23, 2026-07-09).
 * Canonical active paper-trading pair per the 2026-05-24 instrument switch —
 * see jarvis-trader/CLAUDE.md "Active Instruments". Mirrors
 * `engine/backtest/signals.py::DEFAULT_BRIEFING_SYMBOLS` (TS/Python can't
 * share a literal source, so this is the dashboard-side twin) — update both
 * together if the active pair ever changes again.
 */
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
