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

/**
 * "MES/MGC" — human-readable label for the preferred baseline pair, for UI
 * copy that used to hardcode the stale "MCL/MNQ preferred" string (D2-03-v2,
 * 2026-07-24 audit). Derived so the label can never drift from
 * DEFAULT_BRIEFING_SYMBOLS again.
 */
export const PREFERRED_BASELINE_LABEL = DEFAULT_BRIEFING_SYMBOLS.join("/");

/** Mirrors engine/backtest/signals.py::DO_NOT_TRADE_SYMBOLS (TS/Python cannot share a literal) -- update both together. Locked to this exact value by tests/symbol-status-halt-parity.node.test.ts. */
export const HALTED_SYMBOLS = ["MCL", "MNQ", "M2K"] as const;

export function symbolTradeStatus(sym: string): "APPROVED" | "HALTED" {
  return (HALTED_SYMBOLS as readonly string[]).includes(sym.toUpperCase()) ? "HALTED" : "APPROVED";
}

/**
 * The subset of HALTED_SYMBOLS this component set's INSTRUMENT_STATUS table
 * actually tracks. M2K has no dashboard view in this component set (see
 * HALTED_SYMBOLS above for the full authoritative engine halt list) so it's
 * intentionally excluded here — add it if a consumer ever needs it.
 */
const DASHBOARD_HALTED_SYMBOLS = ["MCL", "MNQ"] as const;

/** Every symbol this component set knows about, active pair first. */
export const ALL_TRACKED_SYMBOLS = [
  ...DEFAULT_BRIEFING_SYMBOLS,
  ...DASHBOARD_HALTED_SYMBOLS,
] as const;

export type TrackedSymbol = (typeof ALL_TRACKED_SYMBOLS)[number];

/**
 * Static WFE ("Deflated Sharpe" in some UI copy) + approval status per
 * instrument, mirroring live gate-v2 reality — the same values already
 * encoded in `app/command-center/constants.ts::INSTRUMENTS` (kept in sync
 * manually; that file is page-scoped and out of scope for this fix, this is
 * the shared-lib twin other components should read from). MES/MGC are the
 * actively-traded pair; MCL/MNQ are HALTED (routing-blocked).
 */
export const INSTRUMENT_STATUS: Record<
  TrackedSymbol,
  { wfe: number; status: "APPROVED" | "HALTED"; timeframe: string }
> = {
  MES: { wfe: 1.0, status: "APPROVED", timeframe: "1h" },
  MGC: { wfe: 1.0, status: "APPROVED", timeframe: "1d" },
  MCL: { wfe: 0.0, status: "HALTED", timeframe: "1h" },
  MNQ: { wfe: 0.0, status: "HALTED", timeframe: "1h" },
};
