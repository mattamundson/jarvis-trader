// Trading Eligibility panel — pure data transforms (PRB-25).
//
// WHY: docs/CURRENT_STATE.md used to be the only place that answered "is
// symbol X currently approved to paper-trade?" — a hand-maintained markdown
// table that drifted from live gate reality repeatedly (confirmed stale
// twice in one night: 2026-07-29). The fix isn't re-syncing the doc once,
// it's making the eligibility view structurally incapable of drifting by
// deriving every row directly from the engine's live
// `GET /paper/validation/approved-paper-gates` response, with zero
// hardcoded symbol list on the dashboard side. If the engine's
// APPROVED_PAPER_SYMBOLS ever changes, this view updates on the next poll
// with no dashboard-side edit required.
//
// Split out of app/trading-eligibility/page.tsx (mirrors the
// instrumentValidationRows.ts / processSupervision.ts precedent in this
// repo) so the transform is unit-testable without rendering JSX.

import type {
  ApprovedInstrumentGateRow,
  ApprovedPaperGatesResponse,
  ApprovedPaperValidationGate,
} from "@/lib/api";

export type EligibilityTone = "bull" | "bear" | "warn" | "neutral";

export interface EligibilityRow {
  symbol: string;
  overallPass: boolean;
  tone: EligibilityTone;
  label: string;
  tradeCount: number;
  daysWithTrades: number;
  gates: ApprovedPaperValidationGate[];
  failingGateNames: string[];
}

/**
 * Live approved-paper-gates response -> per-symbol display rows. Every field
 * here is read straight off `data.instruments` — no override table, no
 * "MES/MGC are always APPROVED" style hardcoding. A symbol whose gates
 * degrade is reflected here on the next poll; nothing here can go stale the
 * way the markdown table did.
 */
export function eligibilityRows(
  data: ApprovedPaperGatesResponse | undefined
): EligibilityRow[] {
  if (!data?.instruments) return [];
  return data.instruments.map((inst) => buildRow(inst));
}

function buildRow(inst: ApprovedInstrumentGateRow): EligibilityRow {
  const failingGateNames = inst.gates
    .filter((g) => !g.passes)
    .map((g) => g.name);
  return {
    symbol: inst.symbol,
    overallPass: inst.overall_pass,
    tone: inst.overall_pass ? "bull" : "bear",
    label: inst.overall_pass ? "ELIGIBLE" : "NOT ELIGIBLE",
    tradeCount: inst.trade_count,
    daysWithTrades: inst.days_with_trades,
    gates: inst.gates,
    failingGateNames,
  };
}

export function eligibleCount(rows: EligibilityRow[]): number {
  return rows.filter((r) => r.overallPass).length;
}

/** Format a gate's current/target value with its unit, honestly showing "—" for non-finite values instead of "NaN" or "0". */
export function formatGateValue(value: number, unit: string): string {
  if (!Number.isFinite(value)) return "—";
  const formatted = Number.isInteger(value) ? String(value) : value.toFixed(2);
  return unit ? `${formatted}${unit}` : formatted;
}

/** Symbols the live endpoint actually returned — used to render an honest "not tracked here" caveat rather than silently omitting instruments a reader might expect (e.g. a symbol traded via a different path than APPROVED_PAPER_SYMBOLS). */
export function trackedSymbols(data: ApprovedPaperGatesResponse | undefined): string[] {
  return (data?.instruments ?? []).map((i) => i.symbol);
}
