// Strategy C+ "Additional metrics" tile row — pure derivation, isolated from
// app/strategy-c/page.tsx so it's independently testable (no React renderer
// is installed in this project; see tests/strategyCTiles.node.test.ts).
//
// GT-12: the "Final Equity" tile used to render final_equity (a dollar
// figure, e.g. $412,306.24) but appended a "x" suffix as if it were the
// equity-curve multiple, and its offline placeholder was the multiple
// (4.12x) hardcoded under the "Final Equity" label. Keep final_equity
// (dollars) and final_multiple_x (ratio) as two distinct, correctly-labeled
// tiles — never conflate them again.

export interface StrategyCFullPeriod {
  sortino?: number | null;
  calmar?: number | null;
  win_rate?: number | null;
  final_equity?: number | null;
  final_multiple_x?: number | null;
}

export interface StrategyCTile {
  label: string;
  live: boolean;
  value: string;
}

export function fmtPctTile(v: number | null | undefined, decimals = 1): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(decimals)}%`;
}

export function fmtNumTile(v: number | null | undefined, decimals = 2): string {
  if (v == null) return "—";
  return v.toFixed(decimals);
}

export function fmtUsdTile(v: number | null | undefined): string {
  if (v == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(v);
}

/**
 * Builds the five "Additional metrics" tiles shown under the Strategy C+
 * IS/OOS panel. Each tile carries `live: false` (and a "Static" badge in the
 * UI) whenever the engine metrics endpoint didn't return that field. A
 * missing metric renders as "—" (absent), never a fabricated/invented
 * number — a plausible-looking placeholder would be indistinguishable from
 * real backtest output at a glance, badge or no badge.
 */
export function buildAdditionalMetricsTiles(
  fullPeriod: StrategyCFullPeriod | null | undefined
): StrategyCTile[] {
  return [
    {
      label: "Sortino",
      live: fullPeriod?.sortino != null,
      value: fmtNumTile(fullPeriod?.sortino),
    },
    {
      label: "Calmar",
      live: fullPeriod?.calmar != null,
      value: fmtNumTile(fullPeriod?.calmar),
    },
    {
      label: "Win Rate",
      live: fullPeriod?.win_rate != null,
      value: fmtPctTile(fullPeriod?.win_rate),
    },
    {
      label: "Final Equity",
      live: fullPeriod?.final_equity != null,
      value: fmtUsdTile(fullPeriod?.final_equity),
    },
    {
      label: "Final Multiple",
      live: fullPeriod?.final_multiple_x != null,
      value:
        fullPeriod?.final_multiple_x != null
          ? `${fmtNumTile(fullPeriod.final_multiple_x)}×`
          : "—",
    },
  ];
}
