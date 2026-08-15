import type {
  ApprovedInstrumentGateRow,
  ApprovedPaperGatesResponse,
} from "@/lib/api";

export interface InstrumentValidationRow {
  symbol: string;
  pf: number | null;
  sharpe: number | null;
  wr: number | null;
  status: "APPROVED" | "REVIEWING";
  badgeVariant: "bull" | "info";
}

function gateValue(
  row: ApprovedInstrumentGateRow,
  names: readonly string[],
): number | null {
  const gate = row.gates.find((g) => names.includes(g.name));
  return gate?.current ?? null;
}

/**
 * Builds the Instrument Validation Scorecard's rows directly from the
 * `/paper/validation/approved-paper-gates` response — no hardcoded symbol
 * list. Prior versions of this widget hardcoded MCL/MNQ as permanently
 * "APPROVED", which the API never returns (APPROVED_PAPER_SYMBOLS is
 * MES/MGC), silently misrepresenting two DO_NOT_TRADE_SYMBOLS-halted
 * instruments as approved and trading while omitting the real approved pair.
 */
export function buildInstrumentValidationRows(
  data: ApprovedPaperGatesResponse | undefined,
): InstrumentValidationRow[] {
  if (!data?.instruments) return [];

  return data.instruments.map((inst) => ({
    symbol: inst.symbol,
    pf: gateValue(inst, ["profit_factor"]),
    sharpe: gateValue(inst, ["sharpe_ratio"]),
    wr: gateValue(inst, ["win_rate", "wr"]),
    status: inst.overall_pass ? "APPROVED" : "REVIEWING",
    badgeVariant: inst.overall_pass ? "bull" : "info",
  }));
}
