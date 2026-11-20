/**
 * Kill-switch drawdown projection.
 *
 * Current drawdown and the halt come from GET /safety/status. The peak
 * sentence is matched to GET /portfolio/history/equity-curve ending
 * balances. Those balances are the stored daily_pnl.ending_balance values.
 * Do not rebuild them as a fresh cumulative of realized_pnl.
 *
 * EQUITY_CURVE_DAYS is the single lookback used by the equity-curve request
 * and by the window note. It is not the engine kill-switch constant.
 */

export const EQUITY_CURVE_DAYS = 90;
export const PAPER_TRADES_LIMIT = 500;
export const PROJECTION_LOADING_COPY = "Loading projection…";
export const PROJECTION_UNAVAILABLE_COPY = "Projection unavailable";

export interface DrawdownProjection {
  current_dd_pct: number;
  avg_loss_dollars: number;
  portfolio_equity: number;
  peak_equity: number;
  max_drawdown_pct: number;
  dollars_until_halt: number;
  trades_remaining: number;
  streak: number[];
}

export interface EquityCurvePoint {
  date: string;
  equity: number;
}

export interface HaltPeakAudit {
  sentence: string;
  peakEquity: number | null;
  peakDate: string | null;
  matched: boolean;
}

export interface ClosedTradeRow {
  exit_time?: unknown;
  symbol?: unknown;
  pnl?: unknown;
  status?: unknown;
}

export interface PeakWindowNote {
  sentence: string;
  inside: boolean;
  leavesOn: string | null;
  nextDate: string | null;
  nextEquity: number | null;
  previewFraction: number | null;
}

export interface SafetyProjectionInput {
  drawdown_pct?: number;
  drawdown_limit_pct?: number;
  portfolio_equity?: number;
  equity_peak?: number;
}

export interface ReadyProjectionCard {
  status: "ready";
  projection: DrawdownProjection;
  peakAudit: string;
  detailLines: string[];
}

export interface UnavailableProjectionCard {
  status: "unavailable";
}

export type ProjectionCardState = ReadyProjectionCard | UnavailableProjectionCard;

const HISTORY_MATCH_TOLERANCE = 0.02;

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
    avgLoss > 0
      ? Math.max(0, Math.floor(dollarsUntilHalt / avgLoss))
      : Number.POSITIVE_INFINITY;
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
    dollars_until_halt: dollarsUntilHalt,
    trades_remaining: tradesLeft,
    streak,
  };
}

export function impliedHaltPeak(equity: number, drawdownFraction: number): number | null {
  const current = Math.abs(drawdownFraction);
  if (!(equity > 0) || !(current < 1) || !Number.isFinite(current) || !Number.isFinite(equity)) {
    return null;
  }
  return equity / (1 - current);
}

export function formatUsd(amount: number): string {
  const negative = amount < 0;
  const [whole, frac] = Math.abs(amount).toFixed(2).split(".");
  const withCommas = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "-" : ""}$${withCommas}.${frac}`;
}

function formatHaltPercent(pct: number): string {
  const rounded = Math.round(pct * 100) / 100;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2);
}

function utcDay(value: string): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  if (
    parsed.getUTCFullYear() !== year ||
    parsed.getUTCMonth() !== month - 1 ||
    parsed.getUTCDate() !== day
  ) {
    return null;
  }
  return parsed.toISOString().slice(0, 10);
}

function addUtcDays(isoDay: string, days: number): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDay);
  if (!match) return null;
  const parsed = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  parsed.setUTCDate(parsed.getUTCDate() + days);
  return parsed.toISOString().slice(0, 10);
}

function closerPoint(
  current: EquityCurvePoint | null,
  candidate: EquityCurvePoint,
  implied: number,
): EquityCurvePoint {
  if (!current) return candidate;
  const currentDiff = Math.abs(current.equity - implied);
  const candidateDiff = Math.abs(candidate.equity - implied);
  if (candidateDiff < currentDiff - 1e-9) return candidate;
  if (currentDiff < candidateDiff - 1e-9) return current;
  return candidate.date >= current.date ? candidate : current;
}

/**
 * Match the halt's implied peak to a stored ending_balance.
 * A miss prints the implied peak and does not invent a date.
 */
export function haltPeakAuditSentence(
  equity: number,
  drawdownFraction: number,
  points: EquityCurvePoint[],
): HaltPeakAudit {
  const implied = impliedHaltPeak(equity, drawdownFraction);
  if (implied == null) {
    return {
      sentence: "history row did not match the halt peak",
      peakEquity: null,
      peakDate: null,
      matched: false,
    };
  }

  let best: EquityCurvePoint | null = null;
  for (const point of points) {
    if (!point || !Number.isFinite(point.equity) || !point.date) continue;
    best = closerPoint(best, point, implied);
  }

  const bestDiff = best ? Math.abs(best.equity - implied) : Infinity;
  if (!best || bestDiff > HISTORY_MATCH_TOLERANCE) {
    return {
      sentence: `Peak ${formatUsd(implied)} · history row did not match the halt peak`,
      peakEquity: implied,
      peakDate: null,
      matched: false,
    };
  }

  const peakDate = best.date.slice(0, 10);
  return {
    sentence: `Peak ${formatUsd(best.equity)} on ${peakDate} · whole closed book · 90-day ending_balance · halt uses this`,
    peakEquity: best.equity,
    peakDate,
    matched: true,
  };
}

function laterHigh(current: EquityCurvePoint | null, candidate: EquityCurvePoint): EquityCurvePoint {
  if (!current) return candidate;
  if (candidate.equity > current.equity + 1e-9) return candidate;
  if (current.equity > candidate.equity + 1e-9) return current;
  return candidate.date >= current.date ? candidate : current;
}

export function peakWindowNote(
  peakDate: string,
  points: EquityCurvePoint[],
  liveEquity: number,
  asOf: string,
  lookbackDays = EQUITY_CURVE_DAYS,
): PeakWindowNote {
  const peakDay = utcDay(peakDate);
  const asOfDay = utcDay(asOf);
  const leavesOn = peakDay ? addUtcDays(peakDay, lookbackDays + 1) : null;
  const inside = Boolean(peakDay && asOfDay && leavesOn && asOfDay < leavesOn);

  let next: EquityCurvePoint | null = null;
  if (peakDay) {
    for (const point of points) {
      const pointDay = point?.date ? utcDay(point.date) : null;
      if (!pointDay || pointDay <= peakDay || !Number.isFinite(point.equity)) continue;
      next = laterHigh(next, { date: pointDay, equity: point.equity });
    }
  }

  const nextEquity = next ? next.equity : null;
  const nextDate = next ? next.date : null;
  const previewFraction =
    nextEquity != null && nextEquity > 0 && Number.isFinite(liveEquity)
      ? (nextEquity - liveEquity) / nextEquity
      : null;

  const timing = !leavesOn
    ? "This peak row has no window date"
    : inside
      ? `This peak row leaves the ${lookbackDays}-day window on ${leavesOn} UTC`
      : `This peak row left the ${lookbackDays}-day window on ${leavesOn} UTC`;

  const outlook =
    next && previewFraction != null
      ? ` Preview of the stored high that would remain: ${formatUsd(next.equity)} on ${next.date} (${(previewFraction * 100).toFixed(2)}%) — not the live halt.`
      : " There is no later stored high.";

  return {
    sentence: `${timing}.${outlook}`,
    inside,
    leavesOn,
    nextDate,
    nextEquity,
    previewFraction,
  };
}

export function haltGapSentence(dollarsUntilHalt: number, haltPercent: number): string {
  return `Gap ${formatUsd(dollarsUntilHalt)} to the ${formatHaltPercent(haltPercent)}% halt`;
}

function finitePnl(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function symbolSplitSentence(
  trades: ClosedTradeRow[],
  peakDate: string,
  limit = PAPER_TRADES_LIMIT,
): string | null {
  const peakDay = utcDay(peakDate);
  if (!peakDay) return null;

  const exitDays: string[] = [];
  for (const trade of trades) {
    if (typeof trade?.exit_time !== "string") continue;
    const day = utcDay(trade.exit_time);
    if (day) exitDays.push(day);
  }
  if (trades.length >= limit) {
    const earliest = exitDays.length ? exitDays.reduce((a, b) => (a < b ? a : b)) : null;
    if (!earliest || earliest >= peakDay) return null;
  }

  const totals = new Map<string, number>();
  for (const trade of trades) {
    if (trade?.status != null && String(trade.status).toLowerCase() !== "closed") continue;
    if (typeof trade?.exit_time !== "string") continue;
    const day = utcDay(trade.exit_time);
    if (!day || day <= peakDay) continue;
    const pnl = finitePnl(trade.pnl);
    const symbol = typeof trade.symbol === "string" ? trade.symbol.trim() : "";
    if (pnl == null || !symbol) return null;
    totals.set(symbol, (totals.get(symbol) ?? 0) + pnl);
  }
  if (totals.size === 0) return null;

  const ordered = [...totals.entries()].sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]) || a[0].localeCompare(b[0]));
  const parts = ordered.map(([symbol, pnl]) => `${symbol} ${formatUsd(pnl)}`);
  return `Since that peak, closed pnl: ${parts.join(" · ")} · this split does not change the halt`;
}

export function equityPeakDisclaimer(
  payloadPeak: number | null | undefined,
  haltPeak: number | null,
): string | null {
  if (typeof payloadPeak !== "number" || !Number.isFinite(payloadPeak)) return null;
  if (haltPeak == null || !Number.isFinite(haltPeak)) return null;
  const payloadCents = Math.round(payloadPeak * 100);
  const haltCents = Math.round(haltPeak * 100);
  if (Math.abs(payloadCents - haltCents) <= HISTORY_MATCH_TOLERANCE * 100) return null;
  return `payload equity_peak is not the halt peak ${formatUsd(payloadPeak)}`;
}

export function projectionCardState(input: {
  failed?: boolean;
  safety: SafetyProjectionInput | null;
  avgLossDollars: number;
  points: EquityCurvePoint[];
  trades: ClosedTradeRow[];
  asOf: string;
}): ProjectionCardState {
  if (input.failed || !input.safety) return { status: "unavailable" };
  const equity = Number(input.safety.portfolio_equity);
  const fraction = Number(input.safety.drawdown_pct ?? 0);
  const projection = buildDrawdownProjection({
    currentDrawdownFraction: fraction,
    haltFraction: Number(input.safety.drawdown_limit_pct ?? -0.2),
    equity,
    avgLossDollars: input.avgLossDollars,
  });
  if (!projection) return { status: "unavailable" };

  const audit = haltPeakAuditSentence(equity, fraction, input.points);
  const detailLines: string[] = [];
  if (audit.matched && audit.peakDate) {
    detailLines.push(
      peakWindowNote(audit.peakDate, input.points, equity, input.asOf).sentence,
    );
    detailLines.push(haltGapSentence(projection.dollars_until_halt, projection.max_drawdown_pct));
    const split = symbolSplitSentence(input.trades, audit.peakDate);
    if (split) detailLines.push(split);
  } else {
    detailLines.push(haltGapSentence(projection.dollars_until_halt, projection.max_drawdown_pct));
  }
  const peakNote = equityPeakDisclaimer(input.safety.equity_peak, audit.peakEquity);
  if (peakNote) detailLines.push(peakNote);

  return {
    status: "ready",
    projection,
    peakAudit: audit.sentence,
    detailLines,
  };
}
