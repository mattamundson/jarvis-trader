import { matchesPreferredBaseline } from "@/lib/approvedSymbols";

/** Trade row on saved backtest JSON (pnl used for avg trade fallback). */
export interface BacktestTradePnlRow {
  pnl?: number;
}

/** Row shape from GET /backtest/results (saved JSON files). */
export interface BacktestBaselineRow {
  symbol?: string;
  interval?: string;
  profit_factor?: number;
  sharpe?: number;
  win_rate?: number;
  total_return?: number;
  n_trades?: number;
  trades_list?: BacktestTradePnlRow[];
  trades?: BacktestTradePnlRow[];
  full_metrics?: {
    profit_factor?: number;
    sharpe_ratio?: number;
    win_rate?: number;
    max_drawdown_pct?: number;
    total_return_pct?: number;
    total_pnl?: number;
    avg_win?: number;
    avg_loss?: number;
    total_trades?: number;
    symbol?: string;
    trades?: BacktestTradePnlRow[];
  };
  _filename?: string;
}

export interface ScorecardBacktestBaseline {
  label: string;
  timeframe: string;
  profitFactor: number | null;
  sharpeRatio: number | null;
  winRatePct: number | null;
  winRateDecimal: number | null;
  maxDrawdownPct: number | null;
  maxDrawdownFraction: number | null;
  totalReturnLabel: string | null;
  totalPnl: number | null;
  avgTradePnl: number | null;
  totalTrades: number | null;
}

/** Prefer MCL/MNQ files; then rows with full_metrics. */
export function pickApprovedBacktestBaseline(
  rows: BacktestBaselineRow[] | undefined
): ScorecardBacktestBaseline | null {
  if (!rows?.length) return null;
  const approved = (r: BacktestBaselineRow) =>
    matchesPreferredBaseline(`${r.symbol ?? ""} ${r._filename ?? ""}`);
  const pool = rows.some(approved) ? rows.filter(approved) : rows;
  const r =
    pool.find(
      (x) =>
        x.full_metrics &&
        (x.full_metrics.profit_factor != null || x.full_metrics.sharpe_ratio != null)
    ) ??
    pool.find((x) => x.profit_factor != null || x.sharpe != null) ??
    pool[0];
  if (!r) return null;
  const fm = r.full_metrics;
  const pf = fm?.profit_factor ?? r.profit_factor ?? null;
  const sr = fm?.sharpe_ratio ?? r.sharpe ?? null;
  const wrRaw = fm?.win_rate ?? r.win_rate;
  let winRateDecimal: number | null = null;
  let winRatePct: number | null = null;
  if (wrRaw != null && !Number.isNaN(wrRaw)) {
    if (wrRaw > 1) {
      winRatePct = wrRaw;
      winRateDecimal = wrRaw / 100;
    } else {
      winRateDecimal = wrRaw;
      winRatePct = wrRaw * 100;
    }
  }
  const mddRaw = fm?.max_drawdown_pct;
  const maxDrawdownPct = mddRaw == null ? null : Math.abs(mddRaw);
  const maxDrawdownFraction =
    maxDrawdownPct == null ? null : -Math.abs(maxDrawdownPct) / 100;
  const tr = fm?.total_return_pct ?? r.total_return;
  const totalReturnLabel =
    tr == null ? null : `${tr >= 0 ? "+" : ""}${Number(tr).toFixed(1)}%`;
  const sym = r.symbol ?? fm?.symbol ?? "Unknown";
  const interval = r.interval ?? "1h";
  const totalPnl = fm?.total_pnl ?? null;
  const totalTrades = fm?.total_trades ?? r.n_trades ?? null;
  let avgTradePnl: number | null = null;
  if (fm?.avg_win != null && fm?.avg_loss != null && totalTrades != null && totalTrades > 0) {
    const wins = Math.round((winRateDecimal ?? 0) * totalTrades);
    const losses = totalTrades - wins;
    if (wins + losses > 0) {
      avgTradePnl = (wins * fm.avg_win + losses * fm.avg_loss) / totalTrades;
    }
  }
  if (avgTradePnl == null) {
    const tl = r.trades_list ?? r.trades ?? fm?.trades;
    if (Array.isArray(tl) && tl.length > 0) {
      const pnls = tl
        .map((t) => Number(t.pnl))
        .filter((n) => !Number.isNaN(n));
      if (pnls.length > 0) {
        avgTradePnl = pnls.reduce((a, b) => a + b, 0) / pnls.length;
      }
    }
  }
  return {
    label: `${sym} — ${interval}`,
    timeframe: `${interval} bars`,
    profitFactor: pf,
    sharpeRatio: sr,
    winRatePct,
    winRateDecimal,
    maxDrawdownPct,
    maxDrawdownFraction,
    totalReturnLabel,
    totalPnl,
    avgTradePnl,
    totalTrades,
  };
}

export function fmtBaselineNum(n: number | null, decimals = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toFixed(decimals);
}
