/**
 * Honest-annualization layer — the single client-side source of truth for
 * ANNUALIZED Sharpe / DSR / CAGR displays.
 *
 * THE PROBLEM (C3 metric-honesty pass, 2026-08-18)
 * ------------------------------------------------
 * Annualizing a per-trade (or per-trade-day) Sharpe by a fixed 252 assumes the
 * strategy trades ~every trading day. Low-frequency strategies were overstated
 * by sqrt(252 / actual_trades_per_year) — measured 3.78x on the MES campaign
 * (17.6 trades/yr), 9.1x on a 3 trades/yr strategy. The engine fixed its
 * backtest path (engine/backtest/metrics.py, commit 435f4964, on master) but
 * the DASHBOARD still rendered as-run 252-annualized numbers in several
 * places, plus hardcoded legacy references (e.g. the old "MES 1h Backtest
 * (Best) — Sharpe 4.16" static block).
 *
 * THE RULE (independent re-verification)
 * --------------------------------------
 * Any annualized metric a panel displays MUST be re-derived here from the raw
 * engine outputs (the deduped trade record or the saved backtest JSON's
 * trades + window dates), never trusted as-is from a single engine field.
 * Formulas mirror the engine's canonical implementations exactly so a number
 * rendered here can be verified against engine outputs:
 *   - trades-per-year: engine/backtest/metrics.py `_annualization_factor`
 *     (window >= 90 days, capped at 2520, else fall back to 252).
 *   - Sharpe: engine/analytics/metrics.py `sharpe(periods_per_year=…)` and
 *     engine/backtest/metrics.py `compute_sharpe_sortino`.
 *   - DSR: engine/backtest/deflated_sharpe.py `deflated_sharpe_ratio`
 *     (closed-form Bailey-López de Prado; RAW native-frequency Sharpe input
 *     only — never an annualized one, per the 2026-07-10 incident where
 *     annualized-input DSR flipped fails into false passes).
 *   - CAGR: compounding over the ACTUAL elapsed calendar span of the record,
 *     not 252 periods per year.
 *
 * "CAGR first": correct CAGR before Sharpe/DSR — CAGR uses the raw elapsed
 * span, Sharpe uses sqrt(observed trades/yr), and DSR is re-deflated from the
 * raw per-trade Sharpe. Order matters because each downstream metric consumes
 * the previous one's honesty.
 */

import { type HonestTrade } from "@/lib/honestTrades";

// ── Constants (mirror engine/backtest/metrics.py) ───────────────────────────

/** Fallback when the record's calendar window is unknown / too short. */
export const DEFAULT_ANNUALIZATION_TRADES_PER_YEAR = 252;
/** Windows shorter than this cannot be honestly annualized. */
export const MIN_ANNUALIZATION_WINDOW_DAYS = 90;
/** Cap on the derived trades-per-year multiplier. */
export const MAX_ANNUALIZATION_TRADES_PER_YEAR = 2520;
/** Days per year used for span→years conversion (matches engine). */
export const DAYS_PER_YEAR = 365.25;

// ── Raw helpers ──────────────────────────────────────────────────────────────

/** ISO timestamp (or date) → epoch ms. NaN for unparseable input. */
function parseMs(iso: string | null | undefined): number {
  if (!iso) return NaN;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? NaN : ms;
}

/**
 * Calendar days between two ISO timestamps, or null when either is missing.
 * The engine spans backtest windows inclusive of both endpoints; for the
 * trade record we span first-exit → last-exit (the window the trades actually
 * cover). A negative/zero span yields null.
 */
export function spanDays(
  fromIso: string | null | undefined,
  toIso: string | null | undefined,
): number | null {
  const a = parseMs(fromIso);
  const b = parseMs(toIso);
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  const days = (b - a) / 86_400_000;
  return days > 0 ? days : null;
}

/**
 * Observed trades-per-year from a count and a calendar window, mirroring
 * engine `_annualization_factor` fallback rules exactly:
 *   - unknown/short (< MIN_ANNUALIZATION_WINDOW_DAYS) window → null
 *     (callers fall back to DEFAULT_ANNUALIZATION_TRADES_PER_YEAR, i.e. the
 *     value is not honestly annualizable and MUST NOT be presented as such)
 *   - observed frequency = nTrades / (spanDays / DAYS_PER_YEAR), capped at
 *     MAX_ANNUALIZATION_TRADES_PER_YEAR.
 */
export function tradesPerYear(
  nTrades: number,
  fromIso: string | null | undefined,
  toIso: string | null | undefined,
): number | null {
  const days = spanDays(fromIso, toIso);
  if (days === null || days < MIN_ANNUALIZATION_WINDOW_DAYS) return null;
  const tpy = nTrades / (days / DAYS_PER_YEAR);
  if (!Number.isFinite(tpy) || tpy <= 0) return null;
  return Math.min(tpy, MAX_ANNUALIZATION_TRADES_PER_YEAR);
}

/**
 * Elapsed calendar years of the trade record (first exit → last exit), or
 * null when there are fewer than 2 timestamped trades. CAGR denominator.
 */
export function recordYears(trades: HonestTrade[]): number | null {
  const times = trades
    .map((t) => parseMs(t.exit_time))
    .filter((ms) => !Number.isNaN(ms));
  if (times.length < 2) return null;
  const ms = Math.max(...times) - Math.min(...times);
  if (ms <= 0) return null;
  return ms / 86_400_000 / DAYS_PER_YEAR;
}

/** Earliest exit timestamp in the record, or null. */
export function firstExit(trades: HonestTrade[]): string | null {
  const times = trades
    .map((t) => t.exit_time)
    .filter((t): t is string => !!t && !Number.isNaN(Date.parse(t)));
  if (!times.length) return null;
  return times.reduce((a, b) => (Date.parse(a) <= Date.parse(b) ? a : b));
}

/** Latest exit timestamp in the record, or null. */
export function lastExit(trades: HonestTrade[]): string | null {
  const times = trades
    .map((t) => t.exit_time)
    .filter((t): t is string => !!t && !Number.isNaN(Date.parse(t)));
  if (!times.length) return null;
  return times.reduce((a, b) => (Date.parse(a) >= Date.parse(b) ? a : b));
}

/**
 * Observed trades-per-year of the deduped trade record itself (n / span).
 * Null when the record cannot be honestly annualized (< 90-day window).
 */
export function recordTradesPerYear(trades: HonestTrade[]): number | null {
  return tradesPerYear(trades.length, firstExit(trades), lastExit(trades));
}

// ── Sharpe ───────────────────────────────────────────────────────────────────

/**
 * Per-trade Sharpe (mean / sample-stdev of trade P&L). Returns null with
 * fewer than 2 trades or zero variance. Mirrors lib/honestTrades.perTradeSharpe
 * — kept here so the annualization family is self-contained.
 */
export function perTradeSharpeRaw(trades: HonestTrade[]): number | null {
  const n = trades.length;
  if (n < 2) return null;
  const mean = trades.reduce((s, t) => s + t.pnl, 0) / n;
  const variance = trades.reduce((s, t) => s + (t.pnl - mean) ** 2, 0) / (n - 1);
  const sd = Math.sqrt(variance);
  if (sd === 0) return null;
  return mean / sd;
}

/**
 * Honest ANNUALIZED Sharpe for the trade record:
 *   perTradeSharpe × sqrt(observed trades-per-year)
 *
 * This is exactly the "deflate by sqrt(252/actual_trades_per_yr)" correction:
 * an as-run 252-annualized Sharpe × sqrt(actual/252) equals this same value.
 * Returns null when the record can't be honestly annualized (short window) or
 * the raw Sharpe is undefined — NEVER falls back to the 252-scaled number.
 */
export function annualizedSharpe(
  trades: HonestTrade[],
  tpy: number | null = recordTradesPerYear(trades),
): number | null {
  const raw = perTradeSharpeRaw(trades);
  if (raw === null) return null;
  if (tpy === null) return null; // not honestly annualizable
  return raw * Math.sqrt(tpy);
}

/**
 * Deflate an as-run 252-annualized Sharpe to the honest value:
 *   engineSharpe252 × sqrt(tpy / 252)
 * (equivalently: divide by sqrt(252 / tpy)). Null tpy → null (cannot verify,
 * fail-conservative: render "—", never a live figure).
 */
export function deflateSharpe(
  engineSharpe252: number | null | undefined,
  tpy: number | null,
): number | null {
  if (engineSharpe252 == null || !Number.isFinite(engineSharpe252)) return null;
  if (tpy == null || tpy <= 0 || !Number.isFinite(tpy)) return null;
  return engineSharpe252 * Math.sqrt(tpy / DEFAULT_ANNUALIZATION_TRADES_PER_YEAR);
}

// ── CAGR ─────────────────────────────────────────────────────────────────────

/**
 * Honest CAGR from the deduped trade record:
 *   (1 + netPnl / startingCapital) ^ (1 / elapsedYears) − 1
 *
 * Compounding uses the ACTUAL elapsed calendar span (first exit → last exit),
 * not 252 fixed periods per year — the "CAGR first" correction. Returns null
 * when the record can't support it (fewer than 2 timestamped trades, no
 * positive capital base, or a return ≤ −100%).
 */
export function honestCagr(
  trades: HonestTrade[],
  startingCapital: number,
): number | null {
  if (!Number.isFinite(startingCapital) || startingCapital <= 0) return null;
  const years = recordYears(trades);
  if (years === null || years <= 0) return null;
  // Same honesty rule as the engine's annualization factor: a sub-90-day
  // window cannot be extrapolated to a year (a 19-day record would otherwise
  // report a wildly overstated CAGR). Null → render "—", never a figure.
  if (years * DAYS_PER_YEAR < MIN_ANNUALIZATION_WINDOW_DAYS) return null;
  const net = trades.reduce((s, t) => s + t.pnl, 0);
  const totalReturn = net / startingCapital;
  if (totalReturn <= -1) return null; // account wiped: CAGR undefined
  const cagr = Math.pow(1 + totalReturn, 1 / years) - 1;
  return Number.isFinite(cagr) ? cagr : null;
}

// ── DSR (re-deflated) ────────────────────────────────────────────────────────

/** Sample skewness (adjusted Fisher–Pearson G1), matching scipy bias=False. */
export function sampleSkewness(values: number[]): number {
  const n = values.length;
  if (n < 3) return 0;
  const mean = values.reduce((s, v) => s + v, 0) / n;
  const m2 = values.reduce((s, v) => s + (v - mean) ** 2, 0);
  const m3 = values.reduce((s, v) => s + (v - mean) ** 3, 0);
  if (m2 === 0) return 0;
  const g1 = (Math.sqrt(n) * m3) / Math.pow(m2, 1.5);
  // bias correction (Fisher): G1 * sqrt(n(n-1)) / (n-2)
  return (g1 * Math.sqrt(n * (n - 1))) / (n - 2);
}

/** Sample excess kurtosis (Fisher, bias=False), matching scipy. */
export function sampleExcessKurtosis(values: number[]): number {
  const n = values.length;
  if (n < 4) return 0;
  const mean = values.reduce((s, v) => s + v, 0) / n;
  const m2 = values.reduce((s, v) => s + (v - mean) ** 2, 0);
  const m4 = values.reduce((s, v) => s + (v - mean) ** 4, 0);
  if (m2 === 0) return 0;
  const g2 = (n * m4) / (m2 * m2) - 3;
  return ((n - 1) / ((n - 2) * (n - 3))) * ((n + 1) * g2 + 6);
}

/** Standard normal CDF via Abramowitz–Stegun 7.1.26 (|err| < 1.5e-7). */
export function normalCdf(z: number): number {
  if (!Number.isFinite(z)) return z > 0 ? 1 : 0;
  const sign = z < 0 ? -1 : 1;
  const x = Math.abs(z) / Math.SQRT2;
  // erf approximation (A&S 7.1.26)
  const t = 1 / (1 + 0.3275911 * x);
  const poly =
    t *
    (0.254829592 +
      t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))));
  const erf = 1 - poly * Math.exp(-x * x);
  return 0.5 * (1 + sign * erf);
}

const EULER_MASCHERONI = 0.5772156649015329;

/** E[max SR | N, null] — engine deflated_sharpe._expected_max_sharpe. */
export function expectedMaxSharpe(nTrials: number): number {
  if (nTrials < 2) return 0;
  const q1 = inverseNormalCdf(1 - 1 / nTrials);
  const q2 = inverseNormalCdf(1 - 1 / (nTrials * Math.E));
  return (1 - EULER_MASCHERONI) * q1 + EULER_MASCHERONI * q2;
}

/** Inverse normal CDF (Acklam's rational approximation, ~1.15e-9). */
function inverseNormalCdf(p: number): number {
  if (p <= 0) return -Infinity;
  if (p >= 1) return Infinity;
  const a = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2, 1.38357751867269e2, -3.066479806614716e1, 2.506628277459239];
  const b = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2, 6.680131188771972e1, -1.328068155288572e1];
  const c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416];
  const plow = 0.02425;
  const phigh = 1 - plow;
  let q: number, r: number;
  if (p < plow) {
    q = Math.sqrt(-2 * Math.log(p));
    return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  if (p <= phigh) {
    q = p - 0.5;
    r = q * q;
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q /
      (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  }
  q = Math.sqrt(-2 * Math.log(1 - p));
  return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
    ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
}

/** Sharpe standard error (Mertens/Lo), engine deflated_sharpe._sharpe_standard_error. */
export function sharpeStandardError(
  sharpe: number,
  skew: number,
  kurtRaw: number,
  nObs: number,
): number {
  if (nObs < 2) return Infinity;
  const variance =
    (1 - skew * sharpe + ((kurtRaw - 1) / 4) * sharpe ** 2) / (nObs - 1);
  if (variance <= 0) return Infinity;
  return Math.sqrt(variance);
}

export interface DeflatedSharpeResult {
  rawSharpe: number;
  expectedMaxSharpe: number;
  sharpeStdError: number;
  dsr: number; // 0..1; ~0 = indistinguishable from luck across N trials
  passesAt10Pct: boolean;
  dsrDegenerate: boolean;
  nTrials: number;
  nObs: number;
  skew: number;
  kurt: number; // raw kurtosis (Gaussian = 3)
}

/**
 * Closed-form Deflated Sharpe Ratio on the RAW per-trade Sharpe — the
 * "re-deflate DSR" step. Mirrors engine deflated_sharpe_ratio exactly:
 *   - input is the native-frequency Sharpe (never annualized)
 *   - E[max SR | N, null] via the Gumbel approximation
 *   - σ_SR via Mertens/Lo with the observed skew/kurtosis
 *   - degenerate σ (non-normal SE breakdown) → dsr 0.0, fail-conservative
 *     (the ABSENCE of a usable correction is not evidence of edge).
 * A DSR near 1 means the observed edge survives the N-trial selection penalty.
 */
export function deflatedSharpeRatio(
  rawSharpe: number,
  nTrials: number,
  nObs: number,
  skew: number,
  kurtRaw: number,
): DeflatedSharpeResult {
  if (nObs < 2 || nTrials < 1) {
    return {
      rawSharpe,
      expectedMaxSharpe: 0,
      sharpeStdError: Infinity,
      dsr: 0,
      passesAt10Pct: false,
      dsrDegenerate: false,
      nTrials,
      nObs,
      skew,
      kurt: kurtRaw,
    };
  }
  const expectedMax = expectedMaxSharpe(nTrials);
  const sigma = sharpeStandardError(rawSharpe, skew, kurtRaw, nObs);
  const degenerate = !Number.isFinite(sigma) || sigma === 0;
  const dsr = degenerate
    ? 0
    : normalCdf((rawSharpe - expectedMax) / sigma);
  return {
    rawSharpe,
    expectedMaxSharpe: expectedMax,
    sharpeStdError: Number.isFinite(sigma) ? sigma : -1,
    dsr,
    passesAt10Pct: dsr >= 0.1,
    dsrDegenerate: degenerate,
    nTrials,
    nObs,
    skew,
    kurt: kurtRaw,
  };
}

/**
 * Re-deflated DSR straight from the deduped trade record: computes the raw
 * per-trade Sharpe, sample skew/kurtosis, then the closed-form DSR with the
 * caller's trial count. `nTrials` = number of parameter combinations that
 * were searched to arrive at this strategy (engine convention: 60 for the
 * strategy-c grid; 1 = no selection-bias penalty).
 */
export function reDeflatedDsr(
  trades: HonestTrade[],
  nTrials: number,
): DeflatedSharpeResult {
  const raw = perTradeSharpeRaw(trades);
  const nObs = trades.length;
  if (raw === null || nObs < 3) {
    return {
      rawSharpe: raw ?? 0,
      expectedMaxSharpe: expectedMaxSharpe(nTrials),
      sharpeStdError: Infinity,
      dsr: 0,
      passesAt10Pct: false,
      dsrDegenerate: nObs < 3,
      nTrials,
      nObs,
      skew: 0,
      kurt: 3,
    };
  }
  const pnls = trades.map((t) => t.pnl);
  const skew = sampleSkewness(pnls);
  const kurtRaw = sampleExcessKurtosis(pnls) + 3;
  return deflatedSharpeRatio(raw, nTrials, nObs, skew, kurtRaw);
}

// ── One-call summary ─────────────────────────────────────────────────────────

export interface HonestAnnualizedSummary {
  trades: number;
  netPnl: number;
  /** Observed trades-per-year, or null when not honestly annualizable. */
  tradesPerYear: number | null;
  /** Honest annualized Sharpe (per-trade × sqrt(tpy)), or null. */
  annualizedSharpe: number | null;
  /** Honest CAGR over the record's actual elapsed span, or null. */
  cagr: number | null;
  /** Re-deflated DSR (raw-frequency input), or null when < 3 trades. */
  dsr: DeflatedSharpeResult | null;
  caveats: string[];
}

/** One-call honest annualized summary for a deduped trade record. */
export function honestAnnualizedSummary(
  trades: HonestTrade[],
  startingCapital: number,
  nTrials: number,
): HonestAnnualizedSummary {
  const caveats: string[] = [];
  const tpy = recordTradesPerYear(trades);
  const years = recordYears(trades);
  if (tpy === null) {
    caveats.push(
      "Record spans fewer than 90 calendar days — annualized Sharpe cannot be honestly computed.",
    );
  }
  if (years === null) {
    caveats.push(
      "Fewer than 2 timestamped trades — CAGR cannot be honestly computed.",
    );
  } else if (years * DAYS_PER_YEAR < MIN_ANNUALIZATION_WINDOW_DAYS) {
    caveats.push(
      "Record spans fewer than 90 calendar days — CAGR cannot be honestly annualized.",
    );
  }
  if (trades.length < 3) {
    caveats.push(
      "Fewer than 3 trades — DSR requires a skew/kurtosis sample and is not computed.",
    );
  }
  return {
    trades: trades.length,
    netPnl: trades.reduce((s, t) => s + t.pnl, 0),
    tradesPerYear: tpy,
    annualizedSharpe: annualizedSharpe(trades, tpy),
    cagr: honestCagr(trades, startingCapital),
    dsr: trades.length >= 3 ? reDeflatedDsr(trades, nTrials) : null,
    caveats,
  };
}

// ── Saved-backtest reference deflation ───────────────────────────────────────

/** Minimal shape of a saved backtest JSON row (/backtest/results). */
export interface SavedBacktestRow {
  start?: string;
  end?: string;
  n_trades?: number;
  sharpe?: number | null;
  full_metrics?: {
    start_date?: string;
    end_date?: string;
    total_trades?: number;
    sharpe_ratio?: number | null;
    total_return_pct?: number | null;
    initial_capital?: number;
    final_capital?: number;
  };
}

/**
 * Honest annualization facts for a saved backtest JSON row: observed
 * trades-per-year from its own window + trade count, and the as-run Sharpe
 * deflated to that frequency. Returns nulls (never fabricated numbers) when
 * the row can't support the derivation.
 */
export function backtestAnnualization(row: SavedBacktestRow): {
  tradesPerYear: number | null;
  deflatedSharpe: number | null;
  honestCagr: number | null;
} {
  const from = row.start ?? row.full_metrics?.start_date;
  const to = row.end ?? row.full_metrics?.end_date;
  const nTrades = row.n_trades ?? row.full_metrics?.total_trades ?? null;
  const asRunSharpe = row.sharpe ?? row.full_metrics?.sharpe_ratio ?? null;
  const tpy =
    nTrades != null ? tradesPerYear(nTrades, from, to) : null;
  let honestCagrVal: number | null = null;
  const ic = row.full_metrics?.initial_capital;
  const fc = row.full_metrics?.final_capital;
  if (ic != null && fc != null && ic > 0 && from && to) {
    const years = spanDays(from, to);
    if (years !== null && years > 0) {
      const totalReturn = fc / ic - 1;
      if (totalReturn > -1) {
        const c = Math.pow(1 + totalReturn, 1 / (years / DAYS_PER_YEAR)) - 1;
        honestCagrVal = Number.isFinite(c) ? c : null;
      }
    }
  }
  return {
    tradesPerYear: tpy,
    deflatedSharpe: deflateSharpe(asRunSharpe, tpy),
    honestCagr: honestCagrVal,
  };
}
