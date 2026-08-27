// Regression tests for the honest-annualization layer (C3 metric-honesty pass).
//
// WHY: the dashboard previously rendered as-run 252-annualized Sharpe values
// (e.g. the hardcoded "MES 1h Backtest (Best) — Sharpe 4.16" static block) and
// engine endpoints still annualize trade-based P&L by a fixed 252, which
// overstates low-frequency strategies by sqrt(252 / actual_trades_per_year).
// These tests lock the DISPLAY-layer correction to hand-computed values AND to
// the engine's canonical formulas (backtest/metrics.py `_annualization_factor`,
// backtest/deflated_sharpe.py `deflated_sharpe_ratio`) so a number rendered
// here is verifiable against engine outputs — the independent re-verification
// rule. Reference values were generated with the engine's own formulas
// (pure-numpy mirror; scipy-norm replaced by the same A&S/Acklam
// approximations this lib uses — agreement is within ~1e-4).
//
// Run: cd dashboard && pnpm run test:unit

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_ANNUALIZATION_TRADES_PER_YEAR,
  MAX_ANNUALIZATION_TRADES_PER_YEAR,
  MIN_ANNUALIZATION_WINDOW_DAYS,
  annualizedSharpe,
  backtestAnnualization,
  deflateSharpe,
  deflatedSharpeRatio,
  expectedMaxSharpe,
  honestCagr,
  honestAnnualizedSummary,
  perTradeSharpeRaw,
  reDeflatedDsr,
  recordTradesPerYear,
  recordYears,
  sampleExcessKurtosis,
  sampleSkewness,
  spanDays,
  tradesPerYear,
} from "../lib/honestAnnualized.ts";
import { type HonestTrade } from "../lib/honestTrades.ts";

const approx = (a: number, b: number, eps = 1e-4) =>
  assert.ok(
    Math.abs(a - b) <= eps,
    `expected ${a} ≈ ${b} (±${eps})`,
  );

function trade(
  pnl: number,
  exitTime: string,
  entryTime = "2019-05-05T12:00:00Z",
): HonestTrade {
  return {
    id: `${pnl}-${exitTime}`,
    symbol: "MES",
    direction: pnl >= 0 ? "LONG" : "SHORT",
    action: pnl >= 0 ? "LONG" : "SHORT",
    entry_time: entryTime,
    exit_time: exitTime,
    pnl,
    pnl_usd: pnl,
    grade: null,
  };
}

/** 128 trades spanning 2019-05-05 → 2026-08-14 (2658 days, ~17.59/yr). */
function mesLikeRecord(): HonestTrade[] {
  const out: HonestTrade[] = [];
  const start = Date.parse("2019-05-05T12:00:00Z");
  const end = Date.parse("2026-08-14T12:00:00Z");
  for (let i = 0; i < 128; i++) {
    const t = new Date(start + ((end - start) * i) / 127);
    out.push(trade(i % 2 === 0 ? 120 : -40, t.toISOString()));
  }
  return out;
}

// ── spanDays / tradesPerYear ─────────────────────────────────────────────────

test("spanDays: calendar days between ISO timestamps, null on bad input", () => {
  assert.equal(spanDays("2026-08-14T00:00:00Z", "2026-08-14T00:00:00Z"), null); // zero span
  approx(spanDays("2026-08-14T00:00:00Z", "2026-08-15T00:00:00Z")!, 1, 1e-9);
  assert.equal(spanDays(null, "2026-08-14T00:00:00Z"), null);
  assert.equal(spanDays("not-a-date", "2026-08-14T00:00:00Z"), null);
  assert.equal(spanDays("2026-08-14T00:00:00Z", "2026-08-13T00:00:00Z"), null); // backwards
});

test("tradesPerYear: MES campaign 128 trades / 2658 days ≈ 17.59 (engine ref)", () => {
  const tpy = tradesPerYear(128, "2019-05-05", "2026-08-14");
  approx(tpy!, 17.5892, 0.02);
});

test("tradesPerYear: null for <90-day window (not honestly annualizable)", () => {
  assert.equal(tradesPerYear(50, "2024-01-01", "2024-02-01"), null);
  assert.equal(tradesPerYear(5, "2024-01-01", "2024-01-15"), null);
});

test("tradesPerYear: null on missing/unparseable window (caller falls back to 252)", () => {
  assert.equal(tradesPerYear(30, "", ""), null);
  assert.equal(tradesPerYear(30, "bad", "worse"), null);
});

test("tradesPerYear: capped at MAX_ANNUALIZATION_TRADES_PER_YEAR", () => {
  const tpy = tradesPerYear(100_000, "2024-01-01", "2025-01-01");
  assert.equal(tpy, MAX_ANNUALIZATION_TRADES_PER_YEAR);
});

test("recordTradesPerYear / recordYears: derived from trade record timestamps", () => {
  const rec = mesLikeRecord();
  approx(recordTradesPerYear(rec)!, 17.5892, 0.02);
  approx(recordYears(rec)!, 2658 / 365.25, 0.02);
  assert.equal(recordTradesPerYear([]), null);
  assert.equal(recordYears([trade(1, "2026-01-01T00:00:00Z")]), null);
});

// ── Sharpe ───────────────────────────────────────────────────────────────────

test("annualizedSharpe: per-trade Sharpe × sqrt(observed tpy), not sqrt(252)", () => {
  const rec = mesLikeRecord();
  const raw = perTradeSharpeRaw(rec)!;
  const tpy = recordTradesPerYear(rec)!;
  approx(annualizedSharpe(rec)!, raw * Math.sqrt(tpy), 1e-9);
  // The 252-inflated value would be raw*sqrt(252) ≈ 3.78x bigger — the exact
  // inflation measured on the MES campaign (engine test_sharpe_annualization).
  const inflated252 = raw * Math.sqrt(252);
  assert.ok(annualizedSharpe(rec)! < inflated252 / 3.5);
});

test("annualizedSharpe: null when the record cannot be honestly annualized", () => {
  // Short window → tpy null → null (never fall back to the 252-scaled number).
  const short = [trade(10, "2024-01-01T00:00:00Z"), trade(-5, "2024-01-20T00:00:00Z")];
  assert.equal(annualizedSharpe(short), null);
  assert.equal(annualizedSharpe([]), null);
  assert.equal(annualizedSharpe([trade(10, "2026-01-01T00:00:00Z")]), null);
});

test("deflateSharpe: the literal sqrt(252/actual) correction (engine ref values)", () => {
  // 2.0878 as-run @252 with 17.5892 trades/yr → 0.5516 (engine measured 0.5517)
  approx(deflateSharpe(2.0878, 17.5892)!, 0.5516, 1e-3);
  approx(deflateSharpe(-0.4621, 17.5892)!, -0.1221, 1e-3);
  // identity: deflating a 252-annualized Sharpe equals raw*sqrt(tpy)
  const raw = 0.114775;
  approx(deflateSharpe(raw * Math.sqrt(252), 17.5892)!, raw * Math.sqrt(17.5892), 1e-6);
});

test("deflateSharpe: null when tpy is unknown (fail-conservative, render '—')", () => {
  assert.equal(deflateSharpe(4.16, null), null);
  assert.equal(deflateSharpe(4.16, undefined), null);
  assert.equal(deflateSharpe(null, 100), null);
  assert.equal(deflateSharpe(4.16, 0), null);
});

test("deflateSharpe: no-op at 252 trades/yr, halves at 63 trades/yr", () => {
  approx(deflateSharpe(2.0, 252)!, 2.0, 1e-9);
  approx(deflateSharpe(2.0, 63)!, 1.0, 1e-9);
});

// ── CAGR ─────────────────────────────────────────────────────────────────────

test("honestCagr: compounds over ACTUAL elapsed years (CAGR first)", () => {
  const rec = [
    trade(500, "2020-01-01T00:00:00Z"),
    trade(750, "2022-01-01T00:00:00Z"),
  ];
  // 2020-01-01 → 2022-01-01 is 731 days (2020 is a leap year).
  const years = recordYears(rec)!;
  approx(years, 731 / 365.25, 1e-9);
  approx(honestCagr(rec, 10_000)!, (1 + 1250 / 10_000) ** (1 / years) - 1, 1e-9);
  // reference: ~2.0y, 12.5% total → ~6.1% (engine ref D: 0.06066017)
  approx(honestCagr(rec, 10_000)!, 0.06066, 5e-3);
});

test("honestCagr: null guards (no capital, single timestamp, wiped account)", () => {
  assert.equal(honestCagr([], 10_000), null);
  assert.equal(honestCagr([trade(10, "2026-01-01T00:00:00Z")], 10_000), null);
  assert.equal(honestCagr([trade(-10_000, "2020-01-01T00:00:00Z"), trade(-100, "2022-01-01T00:00:00Z")], 10_000), null);
  assert.equal(honestCagr([trade(10, "2020-01-01T00:00:00Z"), trade(10, "2022-01-01T00:00:00Z")], 0), null);
});

// ── DSR (re-deflated) ────────────────────────────────────────────────────────

test("sampleSkewness/sampleExcessKurtosis: scipy bias=False conventions", () => {
  // Deterministic series: [100,-60,140,-50,90,-70,120,-40] × 20
  const pattern = [100, -60, 140, -50, 90, -70, 120, -40];
  const pnls = [...Array(20)].flatMap(() => pattern);
  approx(sampleSkewness(pnls), 0.051567, 1e-4); // engine ref C
  approx(sampleExcessKurtosis(pnls) + 3, 1.117706, 1e-4); // raw kurt ref C
  assert.equal(sampleSkewness([1, 2]), 0);
  assert.equal(sampleExcessKurtosis([1, 2, 3]), 0);
});

test("expectedMaxSharpe: Gumbel approximation matches engine values", () => {
  approx(expectedMaxSharpe(1), 0, 1e-9);
  approx(expectedMaxSharpe(3), 0.852804, 1e-4); // engine ref E
  approx(expectedMaxSharpe(10), 1.574598, 1e-4);
  approx(expectedMaxSharpe(60), 2.345338, 1e-4); // engine ref B
});

test("deflatedSharpeRatio: closed-form DSR on RAW Sharpe (engine ref C)", () => {
  const r = deflatedSharpeRatio(0.336341, 1, 160, 0.051567, 1.117706);
  approx(r.expectedMaxSharpe, 0, 1e-9);
  approx(r.sharpeStdError, 0.078747, 1e-3);
  approx(r.dsr, 0.99999, 1e-3);
  assert.equal(r.passesAt10Pct, true);
  assert.equal(r.dsrDegenerate, false);
});

test("deflatedSharpeRatio: high-Sharpe small-sample fails conservatively at 60 trials", () => {
  // 128 trades, raw Sharpe 0.1148, skew -0.0816, kurt 2.6734 → DSR 0.0 @ 60 trials
  const r = deflatedSharpeRatio(0.114775, 60, 128, -0.081629, 2.673395);
  approx(r.expectedMaxSharpe, 2.345338, 1e-4);
  approx(r.sharpeStdError, 0.089393, 1e-3);
  approx(r.dsr, 0.0, 1e-6);
  assert.equal(r.passesAt10Pct, false);
});

test("reDeflatedDsr: computes from trade record at native frequency (never annualized)", () => {
  const rec = mesLikeRecord(); // 128 trades, ~17.6/yr — annualized Sharpe ≈ 0.49
  const r = reDeflatedDsr(rec, 60);
  assert.equal(r.dsrDegenerate, false);
  assert.equal(r.nObs, 128);
  // The raw (native-frequency) Sharpe is the DSR input — NOT the 252-annualized
  // value. Feeding the annualized number would flip this fail into a pass
  // (2026-07-10 incident); lock the fail here.
  assert.equal(r.passesAt10Pct, false);
  assert.equal(r.dsr, 0);
  assert.ok(r.rawSharpe < 1.0);
});

test("reDeflatedDsr: degenerate/insufficient records → dsr 0, never a fake pass", () => {
  assert.equal(reDeflatedDsr([], 60).dsr, 0);
  assert.equal(reDeflatedDsr([trade(1, "2026-01-01T00:00:00Z"), trade(2, "2026-01-02T00:00:00Z")], 60).dsr, 0);
});

// ── One-call summary ─────────────────────────────────────────────────────────

test("honestAnnualizedSummary: aggregates all honesty facts + caveats", () => {
  const rec = mesLikeRecord();
  const s = honestAnnualizedSummary(rec, 50_000, 60);
  assert.equal(s.trades, 128);
  approx(s.tradesPerYear!, 17.5892, 0.02);
  assert.ok(s.annualizedSharpe !== null);
  assert.ok(s.cagr !== null);
  assert.ok(s.dsr !== null);
  assert.deepEqual(s.caveats, []);
});

test("honestAnnualizedSummary: short record surfaces caveats, no fabricated numbers", () => {
  const short = [trade(10, "2024-01-01T00:00:00Z"), trade(-5, "2024-01-20T00:00:00Z")];
  const s = honestAnnualizedSummary(short, 10_000, 60);
  assert.equal(s.annualizedSharpe, null);
  assert.equal(s.tradesPerYear, null);
  assert.equal(s.cagr, null);
  assert.equal(s.dsr, null);
  assert.ok(s.caveats.length >= 2);
});

// ── Saved-backtest reference deflation (BacktestCompareWidget path) ─────────

test("backtestAnnualization: deflates an as-run 252 Sharpe from the JSON's own window", () => {
  // The old "MES 1h Backtest (Best)" reference: 312 trades, window 2019-05-05 →
  // 2026-08-14 (7.27y → 42.9 trades/yr), as-run Sharpe 4.16 @ 252.
  const row = {
    start: "2019-05-05",
    end: "2026-08-14",
    n_trades: 312,
    sharpe: 4.16,
    full_metrics: {
      start_date: "2019-05-05",
      end_date: "2026-08-14",
      total_trades: 312,
      sharpe_ratio: 4.16,
      initial_capital: 50_000,
      final_capital: 73_600,
    },
  };
  const a = backtestAnnualization(row);
  approx(a.tradesPerYear!, 42.88, 0.02); // 312 / 7.274y
  approx(a.deflatedSharpe!, 4.16 * Math.sqrt(42.88 / 252), 0.02); // ≈ 1.72
  // honest CAGR over the same window: (73600/50000)^(1/7.274) − 1 ≈ 5.5%
  approx(a.honestCagr!, (73_600 / 50_000) ** (1 / 7.274) - 1, 0.005);
});

test("backtestAnnualization: row without window → nulls, never a guess", () => {
  const a = backtestAnnualization({ n_trades: 312, sharpe: 4.16 });
  assert.equal(a.tradesPerYear, null);
  assert.equal(a.deflatedSharpe, null);
  assert.equal(a.honestCagr, null);
});

// ── Sanity: exported constants match engine conventions ─────────────────────

test("constants mirror engine/backtest/metrics.py", () => {
  assert.equal(DEFAULT_ANNUALIZATION_TRADES_PER_YEAR, 252);
  assert.equal(MAX_ANNUALIZATION_TRADES_PER_YEAR, 2520);
  assert.equal(MIN_ANNUALIZATION_WINDOW_DAYS, 90);
});
