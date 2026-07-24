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
