import { type HonestTrade, dailyPnl, perTradeSharpe } from "@/lib/honestTrades";

export interface RollingWindowMetrics {
  days: number;
  window: string;
  tradeCount: number;
  grossPnl: number;
  winRate: number | null;
  avgPnlPerTrade: number | null;
  profitFactor: number | null;
  /** Per-trade Sharpe (mean/stdev of trade P&L). NOT annualized. */
  perTradeSharpeVal: number | null;
  windowStart: string;
  windowEnd: string;
}

/** Trades that closed within the last `days` days (UTC). */
function filterTradesByWindow(trades: HonestTrade[], days: number): HonestTrade[] {
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
  return trades.filter((t) => {
    if (!t.exit_time) return false;
    return Date.parse(t.exit_time) >= cutoff;
  });
}

/**
 * Single source of truth for rolling-window P&L/win-rate/profit-factor/Sharpe
 * math shared by RollingPerformanceWidget (/performance) and
 * RollingPerformanceCard (/readiness). All fields derive from one exact-
 * timestamp trade filter — avoids the two components silently disagreeing
 * on window boundaries via different filtering strategies.
 */
export function deriveRollingWindowMetrics(
  trades: HonestTrade[],
  days: number
): RollingWindowMetrics {
  const windowed = filterTradesByWindow(trades, days);
  const n = windowed.length;

  const grossPnl = windowed.reduce((s, t) => s + t.pnl, 0);
  const wins = windowed.filter((t) => t.pnl > 0);
  const losses = windowed.filter((t) => t.pnl < 0);
  const grossWin = wins.reduce((s, t) => s + t.pnl, 0);
  const grossLoss = Math.abs(losses.reduce((s, t) => s + t.pnl, 0));

  const winRate = n > 0 ? wins.length / n : null;
  const avgPnlPerTrade = n > 0 ? grossPnl / n : null;
  const profitFactor = grossLoss > 0 ? grossWin / grossLoss : null;
  const perTradeSharpeVal = perTradeSharpe(windowed);

  const dp = dailyPnl(windowed);
  const windowStart = dp.length > 0 ? dp[0].date : "";
  const windowEnd = dp.length > 0 ? dp[dp.length - 1].date : "";

  return {
    days,
    window: `${days}d`,
    tradeCount: n,
    grossPnl,
    winRate,
    avgPnlPerTrade,
    profitFactor,
    perTradeSharpeVal,
    windowStart,
    windowEnd,
  };
}
