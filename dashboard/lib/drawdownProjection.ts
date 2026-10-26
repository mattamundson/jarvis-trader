export interface DrawdownProjection {
  /** Current distance below the kill-switch peak, in percent. */
  current_dd_pct: number;
  avg_loss_dollars: number;
  portfolio_equity: number;
  /** Equity peak the current drawdown fraction was measured against. */
  peak_equity: number;
  /** Kill-switch halt, in percent. */
  max_drawdown_pct: number;
  trades_remaining: number;
  streak: number[];
}

/**
 * Project consecutive average losses until the kill switch.
 *
 * `currentDrawdownFraction` is the safety-layer magnitude (0.0648 means
 * 6.48% below peak). Dollars remaining are measured from that same peak,
 * not from closed-trade max drawdown.
 */
export function buildDrawdownProjection(input: {
  currentDrawdownFraction: number;
  haltFraction: number;
  equity: number;
  avgLossDollars: number;
}): DrawdownProjection | null {
  const equity = input.equity;
  const halt = Math.abs(input.haltFraction);
  const current = Math.abs(input.currentDrawdownFraction);
  if (!(equity > 0) || !(halt > 0) || !(current < 1) || !Number.isFinite(current)) {
    return null;
  }

  const avgLoss = Math.abs(input.avgLossDollars);
  const peak = equity / (1 - current);
  const equityAtHalt = peak * (1 - halt);
  const dollarsUntilHalt = equity - equityAtHalt;
  const tradesLeft =
    avgLoss > 0 ? Math.max(0, Math.floor(dollarsUntilHalt / avgLoss)) : Number.POSITIVE_INFINITY;

  const streak: number[] = [];
  let projected = equity;
  const steps = Number.isFinite(tradesLeft) ? Math.min(tradesLeft, 8) : 0;
  for (let i = 0; i < steps; i++) {
    projected -= avgLoss;
    streak.push(projected);
  }

  return {
    current_dd_pct: current * 100,
    avg_loss_dollars: avgLoss,
    portfolio_equity: equity,
    peak_equity: peak,
    max_drawdown_pct: halt * 100,
    trades_remaining: tradesLeft,
    streak,
  };
}
