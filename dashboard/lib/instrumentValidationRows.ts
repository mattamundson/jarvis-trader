import type { ApprovedInstrumentGateRow } from "@/lib/api";
import { ALL_TRACKED_SYMBOLS, INSTRUMENT_STATUS, type TrackedSymbol } from "@/lib/approvedSymbols";

export type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

export interface InstrumentRow {
  symbol: string;
  timeframe: string;
  wfe: number | string;
  pf: number | null;
  sharpe: number | null;
  wr: number | null;
  status: string;
  badgeVariant: BadgeVariant;
}

/**
 * Build one scorecard row for a tracked instrument. Pure (no React) so its
 * correctness — MES/MGC read as APPROVED, MCL/MNQ read as HALTED regardless
 * of what the live gates endpoint returns for them — is unit-testable
 * without rendering. Split out of InstrumentValidationScorecard.tsx
 * (D2-03-v2, 2026-07-24 audit) both for testability (node --test can't parse
 * JSX) and because this used to hardcode MCL/MNQ as the approved pair with
 * static WFE 0.82/0.57 and MES as "Revalidating" — the exact opposite of
 * engine reality (`backtest/signals.py::DO_NOT_TRADE_SYMBOLS` halts
 * MCL/MNQ).
 */
export function buildInstrumentRow(
  symbol: TrackedSymbol,
  instrumentMap: Map<string, ApprovedInstrumentGateRow>
): InstrumentRow {
  const meta = INSTRUMENT_STATUS[symbol];
  const live = instrumentMap.get(symbol);

  if (meta.status === "HALTED") {
    // Halted symbols are routing-blocked — no live paper gates to show even
    // if the engine happens to return a row for them.
    return {
      symbol,
      timeframe: meta.timeframe,
      wfe: meta.wfe.toFixed(2),
      pf: null,
      sharpe: null,
      wr: null,
      status: "HALTED",
      badgeVariant: "bear",
    };
  }

  if (live) {
    const pfGate = live.gates.find((g) => g.name === "profit_factor");
    const sharpeGate = live.gates.find((g) => g.name === "sharpe_ratio");
    const wrGate = live.gates.find((g) => g.name === "win_rate" || g.name === "wr");
    return {
      symbol,
      timeframe: meta.timeframe,
      wfe: meta.wfe.toFixed(2),
      pf: pfGate?.current ?? null,
      sharpe: sharpeGate?.current ?? null,
      wr: wrGate?.current ?? null,
      status: live.overall_pass ? "APPROVED" : "REVIEWING",
      badgeVariant: live.overall_pass ? "bull" : "info",
    };
  }

  return {
    symbol,
    timeframe: meta.timeframe,
    wfe: meta.wfe.toFixed(2),
    pf: null,
    sharpe: null,
    wr: null,
    status: "APPROVED",
    badgeVariant: "bull",
  };
}

export function buildDefaultInstrumentRows(): InstrumentRow[] {
  return ALL_TRACKED_SYMBOLS.map((symbol) => buildInstrumentRow(symbol, new Map()));
}

/**
 * Format a scorecard row's win rate for display (GT-36, 2026-07-28 audit).
 *
 * `row.wr` is already percent-scaled by the time it reaches a row — it comes
 * straight from `wrGate?.current` above, which is sourced from the engine's
 * `/paper/validation/approved-paper-gates` gate object
 * (`engine/routers/paper_validation_router.py::_build_validation_gate_rows`),
 * where `current = round(win_rate_pct, 2)` and `win_rate_pct` is already
 * `winning_trades / total_trades * 100` (the gate also carries `unit: "%"`).
 * InstrumentValidationScorecard.tsx previously re-multiplied this by 100 in
 * its JSX (`${(row.wr * 100).toFixed(0)}%`), turning a real 43.75% win rate
 * into "4375%". Extracted here (mirroring the instrumentValidationRows.ts
 * split for D2-03-v2) so the formatting is unit-testable without rendering
 * JSX.
 */
export function formatWinRatePct(wr: number | null): string {
  return wr !== null ? `${wr.toFixed(0)}%` : "—";
}
