// Honest deduped trade record — the single client-side source of truth for the
// /stats analytics widgets.
//
// WHY: the raw engine endpoints (/portfolio/history/trades, /analytics/performance,
// /analytics/trades/by-symbol, /portfolio/stats/*) over-count re-logged winners
// (~29 raw rows -> 18 real trades), inflating totals (fabricated +$3,899 / PF 2.95
// vs the deduped reality -$8,188 / PF 0.66). master-api's /master/trading/realized
// applies the read-time dedup and returns the canonical trade_list. Every analytics
// widget should derive from THIS, never from the raw lists. See lib/honestMetrics.ts
// and lib/masterApi.ts (fetchRealizedPnl).
//
// The deduped record carries only: symbol, direction, entry_time, exit_time,
// pnl_usd, grade. Anything that needs fields absent here (commissions, quantities,
// fill prices, broker-computed Sharpe) cannot be derived honestly and must be
// surfaced with an explicit caveat rather than a fabricated number.

import { fetchRealizedPnl, type RealizedTrade } from "@/lib/masterApi";

export interface HonestTrade {
  /** stable synthetic key (the deduped record has no trade id) */
  id: string;
  symbol: string;
  /** normalized "LONG" | "SHORT" (see normalizeDirection); rarely other if upstream sends an unknown side */
  direction: string;
  /** alias of direction, for widgets keyed on `action` */
  action: string;
  entry_time: string | null;
  exit_time: string | null;
  /** realized P&L in USD (= pnl_usd) */
  pnl: number;
  pnl_usd: number;
  grade: string | null;
}

export interface HonestTradeSet {
  trades: HonestTrade[];
  net: number;
  wins: number;
  losses: number;
  /** 0..1 */
  winRate: number;
  profitFactor: number | null;
  grossWin: number;
  grossLoss: number;
  headline: string;
  /** un-deduped row count from the engine */
  rawRows: number;
  /** rows collapsed by dedup (rawRows - trades) */
  relogged: number;
  caveats: string[];
}

/**
 * Canonicalize a raw direction/side to "LONG" | "SHORT". The deduped record's
 * `direction` is produced upstream (the engine emits "LONG"/"SHORT", but
 * broker/IB-style feeds use BUY/SELL or B/S), so normalize ONCE here — every
 * widget that splits the record by direction (`t.direction === "LONG"`) then
 * works regardless of upstream casing or convention, and a long/short split can
 * never silently collapse to zero on a casing mismatch. Unrecognized values
 * pass through upper-cased so they stay visible rather than miscounted.
 */
function normalizeDirection(raw: string | null | undefined): string {
  const s = (raw ?? "").trim().toUpperCase();
  if (s === "LONG" || s === "BUY" || s === "BOT" || s === "B") return "LONG";
  if (s === "SHORT" || s === "SELL" || s === "SLD" || s === "S") return "SHORT";
  return s;
}

/** Fetch the deduped trade record. Throws if the honest record is unavailable. */
export async function fetchHonestTrades(): Promise<HonestTradeSet> {
  const p = await fetchRealizedPnl();
  const es = p.engine_sim;
  if (!es?.ok) {
    throw new Error(es?.error || "honest trade record unavailable");
  }
  const trades: HonestTrade[] = (es.trade_list ?? []).map(
    (t: RealizedTrade, i: number) => {
      const direction = normalizeDirection(t.direction);
      return {
        id: `${t.symbol}-${t.entry_time ?? "na"}-${i}`,
        symbol: t.symbol,
        direction,
        action: direction,
        entry_time: t.entry_time,
        exit_time: t.exit_time,
        pnl: t.pnl_usd,
        pnl_usd: t.pnl_usd,
        grade: t.grade,
      };
    },
  );
  return {
    trades,
    net: es.net_realized,
    wins: es.wins,
    losses: es.losses,
    winRate: es.win_rate,
    profitFactor: es.profit_factor ?? null,
    grossWin: es.gross_win,
    grossLoss: es.gross_loss,
    headline: p.headline,
    rawRows: es.raw_rows,
    relogged: Math.max(0, es.raw_rows - es.trades),
    caveats: p.caveats ?? [],
  };
}

// ─── Derivation helpers (pure) ──────────────────────────────────────────────

/** Holding period in minutes, or null if either timestamp is missing/invalid. */
export function durationMinutes(t: HonestTrade): number | null {
  if (!t.entry_time || !t.exit_time) return null;
  const a = Date.parse(t.entry_time);
  const b = Date.parse(t.exit_time);
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  return (b - a) / 60_000;
}

export interface SymbolStat {
  symbol: string;
  trades: number;
  wins: number;
  losses: number;
  winRate: number; // 0..1
  net: number;
  grossWin: number;
  grossLoss: number;
  profitFactor: number | null;
}

/** Per-symbol aggregates, sorted by net P&L descending. */
export function bySymbolStats(trades: HonestTrade[]): SymbolStat[] {
  const map = new Map<string, HonestTrade[]>();
  for (const t of trades) {
    const arr = map.get(t.symbol) ?? [];
    arr.push(t);
    map.set(t.symbol, arr);
  }
  const out: SymbolStat[] = [];
  for (const [symbol, arr] of map) {
    const wins = arr.filter((t) => t.pnl > 0).length;
    const losses = arr.filter((t) => t.pnl < 0).length;
    const grossWin = arr.filter((t) => t.pnl > 0).reduce((s, t) => s + t.pnl, 0);
    const grossLoss = Math.abs(
      arr.filter((t) => t.pnl < 0).reduce((s, t) => s + t.pnl, 0),
    );
    const net = arr.reduce((s, t) => s + t.pnl, 0);
    out.push({
      symbol,
      trades: arr.length,
      wins,
      losses,
      winRate: arr.length ? wins / arr.length : 0,
      net,
      grossWin,
      grossLoss,
      profitFactor: grossLoss > 0 ? grossWin / grossLoss : null,
    });
  }
  return out.sort((a, b) => b.net - a.net);
}

/**
 * Local-calendar date (YYYY-MM-DD) of a trade's close, or null.
 * Uses the local clock (not UTC) so daily/calendar/rolling buckets line up with
 * the calendar widgets — which key on local time. UTC here put evening
 * (US-Central) trades on the next day, shifting the P&L calendar by one.
 */
export function exitDate(t: HonestTrade): string | null {
  if (!t.exit_time) return null;
  const ms = Date.parse(t.exit_time);
  if (Number.isNaN(ms)) return null;
  const d = new Date(ms);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export interface DailyPnl {
  date: string; // YYYY-MM-DD
  pnl: number;
  count: number;
}

/** P&L grouped by close date, ascending. */
export function dailyPnl(trades: HonestTrade[]): DailyPnl[] {
  const map = new Map<string, { pnl: number; count: number }>();
  for (const t of trades) {
    const d = exitDate(t);
    if (!d) continue;
    const cur = map.get(d) ?? { pnl: 0, count: 0 };
    cur.pnl += t.pnl;
    cur.count += 1;
    map.set(d, cur);
  }
  return [...map.entries()]
    .map(([date, v]) => ({ date, ...v }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

export interface EquityPoint {
  /** close timestamp ISO */
  t: string;
  equity: number; // cumulative net P&L
  drawdown: number; // <= 0, distance below running peak
}

/** Cumulative equity + drawdown series, ordered by close time. */
export function equityCurve(trades: HonestTrade[]): EquityPoint[] {
  const sorted = [...trades]
    .filter((t) => t.exit_time)
    .sort((a, b) => Date.parse(a.exit_time!) - Date.parse(b.exit_time!));
  let equity = 0;
  let peak = 0;
  const out: EquityPoint[] = [];
  for (const t of sorted) {
    equity += t.pnl;
    if (equity > peak) peak = equity;
    out.push({ t: t.exit_time!, equity, drawdown: equity - peak });
  }
  return out;
}

/**
 * Fallback starting-capital figure, used only when a caller doesn't have the
 * live value (from /portfolio/stats/paper-phase-summary's `starting_balance`,
 * i.e. settings.INITIAL_CAPITAL) on hand. Same convention as
 * AccountROIWidget.tsx's STARTING_BALANCE_FALLBACK -- never authoritative.
 */
export const DEFAULT_STARTING_CAPITAL = 10_000;

/**
 * Max drawdown as a fraction of account equity (0..1), from the deduped
 * record. Denominated against `Math.max(runningPeak, startingEquity)` rather
 * than the raw cumulative-P&L peak alone -- a peak that is merely
 * tiny-but-positive (e.g. a small early win) previously produced an
 * arbitrarily large drawdown fraction once a later large-dollar loss divided
 * into it (e.g. 1981.7%). Pass the real starting balance when the caller has
 * it (see PaperBalanceWidget.tsx / AccountROIWidget.tsx for the fetch
 * pattern); otherwise DEFAULT_STARTING_CAPITAL floors the denominator so the
 * result can never explode. Single source of truth for every drawdown
 * widget — do not re-derive this loop inline.
 */
export function maxDrawdownPct(
  trades: HonestTrade[],
  startingEquity: number = DEFAULT_STARTING_CAPITAL,
): number {
  let peak = 0;
  let maxDdDollars = 0;
  for (const pt of equityCurve(trades)) {
    if (pt.equity > peak) peak = pt.equity;
    const dd = peak - pt.equity;
    if (dd > maxDdDollars) maxDdDollars = dd;
  }
  const denom = Math.max(peak, startingEquity);
  return denom > 0 ? maxDdDollars / denom : 0;
}

/**
 * Per-trade Sharpe (mean / sample-stdev of trade P&L). This is NOT the engine's
 * annualized Sharpe — it is a deduped trade-level dispersion ratio. Label it as
 * such in the UI. Returns null with < 2 trades or zero variance.
 */
export function perTradeSharpe(trades: HonestTrade[]): number | null {
  const n = trades.length;
  if (n < 2) return null;
  const mean = trades.reduce((s, t) => s + t.pnl, 0) / n;
  const variance =
    trades.reduce((s, t) => s + (t.pnl - mean) ** 2, 0) / (n - 1);
  const sd = Math.sqrt(variance);
  if (sd === 0) return null;
  return mean / sd;
}

/** Stable caveat string for "raw rows collapsed" disclosure. */
export function dedupCaveat(set: HonestTradeSet): string {
  return set.relogged > 0
    ? `${set.trades.length} real trades · ${set.relogged} re-logged rows collapsed`
    : `${set.trades.length} real trades`;
}
