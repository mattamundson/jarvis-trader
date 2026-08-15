/** Resolve the same-day realized value without inferring it from a lifetime field. */
export interface DailyPnlSummaryLike {
  daily_realized_pnl?: unknown;
  /** Legacy alias emitted by older engines. Its scope is endpoint-specific. */
  realized_pnl?: unknown;
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function resolveDailyRealizedPnl(
  summary: DailyPnlSummaryLike | null | undefined,
): number | null {
  if (!summary) return null;
  if (finiteNumber(summary.daily_realized_pnl)) return summary.daily_realized_pnl;
  if (finiteNumber(summary.realized_pnl)) return summary.realized_pnl;
  return null;
}
