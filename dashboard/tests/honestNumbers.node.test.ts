// Numeric-accuracy regression tests for the honest trade-record derivations.
//
// WHY (CLAUDE.md "Verification discipline"): this is a trading system; a
// dashboard that renders a confidently-wrong number (net P&L, win rate, profit
// factor, drawdown, Sharpe) is worse than one that's visibly offline. lib/
// honestTrades.ts + honestMetrics.ts are the single source of truth for those
// numbers and had NO test coverage. These lock each pure transform to
// hand-computed expected values, so a regression in the math becomes a failing
// test instead of a silent lie on the dashboard.
//
// Run: cd dashboard && pnpm run test:unit
//   (node --test --experimental-strip-types "tests/**/*.node.test.ts")
//
// Scope: only timezone-INDEPENDENT assertions. Functions keyed on local-calendar
// date (exitDate/dailyPnl buckets) are asserted via invariants that hold in any
// runner TZ (bucket P&L sums to net, counts sum to trade count), not exact dates.

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  bySymbolStats,
  equityCurve,
  maxDrawdownPct,
  perTradeSharpe,
  durationMinutes,
  dailyPnl,
  dedupCaveat,
  type HonestTrade,
  type HonestTradeSet,
} from "../lib/honestTrades.ts";
import { summarizeRealized } from "../lib/honestMetrics.ts";

// ── Fixture ──────────────────────────────────────────────────────────────────
// Five trades, two symbols, one breakeven (pnl === 0). Noon-UTC exit times so
// ordering is deterministic. Net = 100 - 40 - 30 + 60 + 0 = 90.
function trade(
  symbol: string,
  pnl: number,
  exit_time: string | null,
  entry_time: string | null = "2026-06-01T11:00:00Z",
): HonestTrade {
  return {
    id: `${symbol}-${exit_time ?? "na"}`,
    symbol,
    direction: pnl >= 0 ? "LONG" : "SHORT",
    action: pnl >= 0 ? "LONG" : "SHORT",
    entry_time,
    exit_time,
    pnl,
    pnl_usd: pnl,
    grade: null,
  };
}

const TRADES: HonestTrade[] = [
  trade("MES", 100, "2026-06-01T12:00:00Z"),
  trade("MES", -40, "2026-06-01T13:00:00Z"),
  trade("MGC", -30, "2026-06-01T14:00:00Z"),
  trade("MES", 60, "2026-06-01T15:00:00Z"),
  trade("MGC", 0, "2026-06-01T16:00:00Z"), // breakeven
];
const NET = 90;

const approx = (a: number, b: number, eps = 1e-9) =>
  assert.ok(Math.abs(a - b) <= eps, `expected ${a} ≈ ${b} (±${eps})`);

// ── bySymbolStats ────────────────────────────────────────────────────────────
test("bySymbolStats: per-symbol money math, sorted by net desc", () => {
  const stats = bySymbolStats(TRADES);
  assert.deepEqual(
    stats.map((s) => s.symbol),
    ["MES", "MGC"], // MES net +120 before MGC net -30
  );

  const mes = stats[0];
  assert.equal(mes.trades, 3);
  assert.equal(mes.wins, 2);
  assert.equal(mes.losses, 1);
  approx(mes.net, 120);
  approx(mes.grossWin, 160);
  approx(mes.grossLoss, 40);
  approx(mes.winRate, 2 / 3);
  approx(mes.profitFactor!, 4);

  const mgc = stats[1];
  // breakeven trade IS counted in `trades` but is neither win nor loss —
  // guards against a regression that miscounts 0-P&L trades as wins.
  assert.equal(mgc.trades, 2);
  assert.equal(mgc.wins, 0);
  assert.equal(mgc.losses, 1);
  approx(mgc.net, -30);
  approx(mgc.grossWin, 0);
  approx(mgc.grossLoss, 30);
  approx(mgc.winRate, 0); // 0 wins / 2 trades, NOT 0/1
  approx(mgc.profitFactor!, 0); // grossLoss>0 so 0/30 = 0 (not null)
});

test("bySymbolStats: profitFactor is null only when there are no losses", () => {
  const [only] = bySymbolStats([trade("MES", 50, "2026-06-01T12:00:00Z")]);
  assert.equal(only.grossLoss, 0);
  assert.equal(only.profitFactor, null); // undefined PF, not Infinity
});

// ── equityCurve ──────────────────────────────────────────────────────────────
test("equityCurve: cumulative equity + drawdown vs running peak", () => {
  const curve = equityCurve(TRADES);
  assert.deepEqual(
    curve.map((p) => p.equity),
    [100, 60, 30, 90, 90],
  );
  // drawdown is equity - peak, always <= 0
  assert.deepEqual(
    curve.map((p) => p.drawdown),
    [0, -40, -70, -10, -10],
  );
  approx(curve.at(-1)!.equity, NET); // final equity == net P&L
  assert.ok(curve.every((p) => p.drawdown <= 0));
});

// ── maxDrawdownPct ───────────────────────────────────────────────────────────
test("maxDrawdownPct: worst fractional drop below peak, denominated vs starting capital", () => {
  // peak 100 at T1; trough 30 at T3 => dd$ = 70. Denominator is floored at
  // Math.max(peak, startingEquity) — commit 40113b9 — so with the default
  // 10,000 starting capital this is 70/10000, NOT the unfloored 70/100.
  // (These two assertions were stale from before that commit and were
  // failing on trunk; corrected here while touching this file for the
  // Bug H / T0-07 regression test below.)
  approx(maxDrawdownPct(TRADES), 70 / 10_000, 1e-12);
});

test("maxDrawdownPct: floored-denominator drawdown when peak never rises above zero base", () => {
  const losers = [
    trade("MES", -10, "2026-06-01T12:00:00Z"),
    trade("MES", -5, "2026-06-01T13:00:00Z"),
  ];
  // peak stays 0 (equity never exceeds it), so dd$ = 0 - (-15) = 15 at the
  // trough. Denominator floors to startingEquity (10,000) since peak (0) is
  // smaller -> 15/10000, a small but real (never 0, never NaN/Infinity) drawdown.
  approx(maxDrawdownPct(losers), 15 / 10_000, 1e-12);
});

test("maxDrawdownPct: denominator floor prevents runaway % when peak is tiny (Bug H / T0-07 regression)", () => {
  // A tiny early win establishes a near-zero running peak; a later large-dollar
  // loss previously divided into that tiny peak ALONE in scorecard/page.tsx's
  // now-deleted local computeMaxDDPct(), which had no denominator floor and
  // produced nonsensical values like -1981.7% on live data. maxDrawdownPct()
  // floors the denominator at Math.max(peak, startingEquity) so the result
  // always stays a bounded, sane fraction.
  const tradesTinyPeak: HonestTrade[] = [
    trade("MES", 2, "2026-06-01T12:00:00Z"), // peak = 2
    trade("MES", -2000, "2026-06-01T13:00:00Z"), // equity = -1998, dd$ = 2000
  ];

  // Sanity check: the unfloored (buggy) math this regression test guards
  // against would divide 2000 / 2 = 1000 -> 100000% garbage.
  assert.ok(2000 / 2 > 100, "sanity: unfloored math would be garbage");

  // Floored math: denom = max(peak, DEFAULT_STARTING_CAPITAL) = max(2, 10000).
  approx(maxDrawdownPct(tradesTinyPeak), 2000 / 10_000, 1e-12);
  assert.ok(
    maxDrawdownPct(tradesTinyPeak) < 1,
    "floored drawdown must stay a sane 0..1 fraction, never explode",
  );
});

// ── perTradeSharpe ───────────────────────────────────────────────────────────
test("perTradeSharpe: mean / sample-stdev, hand-computed", () => {
  // pnl [100,-40,-30,60,0]: mean 18, sample var 14480/4 = 3620, sd ≈ 60.1664
  // sharpe = 18 / 60.1664 ≈ 0.29917
  approx(perTradeSharpe(TRADES)!, 0.29917, 1e-4);
});

test("perTradeSharpe: null for <2 trades or zero variance", () => {
  assert.equal(perTradeSharpe([]), null);
  assert.equal(perTradeSharpe([trade("MES", 10, "2026-06-01T12:00:00Z")]), null);
  assert.equal(
    perTradeSharpe([
      trade("MES", 25, "2026-06-01T12:00:00Z"),
      trade("MES", 25, "2026-06-01T13:00:00Z"), // identical -> variance 0
    ]),
    null,
  );
});

// ── durationMinutes ──────────────────────────────────────────────────────────
test("durationMinutes: exact minutes, null on missing/invalid timestamps", () => {
  approx(
    durationMinutes(
      trade("MES", 10, "2026-06-01T13:30:00Z", "2026-06-01T12:00:00Z"),
    )!,
    90,
  );
  assert.equal(durationMinutes(trade("MES", 10, null, "2026-06-01T12:00:00Z")), null);
  assert.equal(durationMinutes(trade("MES", 10, "not-a-date", "2026-06-01T12:00:00Z")), null);
});

// ── dailyPnl (TZ-independent invariants only) ────────────────────────────────
test("dailyPnl: bucket P&L sums to net and counts sum to trade count", () => {
  const buckets = dailyPnl(TRADES);
  approx(buckets.reduce((s, b) => s + b.pnl, 0), NET);
  assert.equal(buckets.reduce((s, b) => s + b.count, 0), TRADES.length);
  // ascending by date string
  const dates = buckets.map((b) => b.date);
  assert.deepEqual(dates, [...dates].sort((a, b) => a.localeCompare(b)));
});

// ── summarizeRealized (honestMetrics) ────────────────────────────────────────
test("summarizeRealized: relogsCollapsed = raw_rows - trades, clamped at 0", () => {
  const s = summarizeRealized({
    engine_sim: {
      net_realized: -1378,
      trades: 18,
      wins: 8,
      losses: 10,
      win_rate: 8 / 18,
      profit_factor: 0.88,
      raw_rows: 24,
      ok: true,
    },
    // fields summarizeRealized does not read:
  } as unknown as Parameters<typeof summarizeRealized>[0]);
  approx(s.netRealized, -1378);
  assert.equal(s.trades, 18);
  assert.equal(s.relogsCollapsed, 6); // 24 raw rows -> 18 real trades
  assert.equal(s.ok, true);
});

test("summarizeRealized: relogsCollapsed never negative when raw_rows < trades", () => {
  const s = summarizeRealized({
    engine_sim: {
      net_realized: 0,
      trades: 5,
      wins: 0,
      losses: 0,
      win_rate: 0,
      profit_factor: 0,
      raw_rows: 3, // inconsistent upstream -> must clamp, not report -2
      ok: true,
    },
  } as unknown as Parameters<typeof summarizeRealized>[0]);
  assert.equal(s.relogsCollapsed, 0);
});

// ── dedupCaveat ──────────────────────────────────────────────────────────────
test("dedupCaveat: discloses collapsed rows only when present", () => {
  const base = { trades: [trade("MES", 1, "2026-06-01T12:00:00Z")] } as HonestTradeSet;
  assert.equal(dedupCaveat({ ...base, relogged: 0 }), "1 real trades");
  assert.equal(
    dedupCaveat({ ...base, relogged: 4 }),
    "1 real trades · 4 re-logged rows collapsed",
  );
});
