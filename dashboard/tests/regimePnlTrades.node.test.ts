// Regression test for GT-28: RegimePnLBreakdownWidget silently rendered
// "Regime data not yet available" (an empty breakdown) despite real closed
// trades with regime labels existing in the DB.
//
// Root cause: `GET /portfolio/history/trades` returns a bare JSON array
// (e.g. `[{...}, {...}]`) -- see engine/routers/portfolio_router.py's
// `portfolio_history_trades()`, which ends with a bare `return out`.
// RegimePnLBreakdownWidget.tsx destructured `json.trades` off that
// response -- `undefined` on a bare array -- so `setTrades(json.trades ??
// [])` always set an empty list, and the per-regime P&L table never
// populated. No error was ever surfaced; the widget looked "quiet" instead
// of broken.
//
// This locks in parseTradesHistoryResponse's array-or-wrapper parsing so a
// regression (e.g. someone reverting to a bare `json.trades ?? []` read)
// fails a test instead of silently reintroducing the bug.
//
// Run: cd dashboard && pnpm run test:unit
//   (node --test --experimental-strip-types "tests/**/*.node.test.ts")

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  parseTradesHistoryResponse,
  type RegimeTradeRecord,
} from "../lib/regimePnlTrades.ts";

// Realistic fixture: the actual bare-array shape portfolio_router.py's
// `portfolio_history_trades()` returns for closed MES/MGC paper trades,
// including both regime sourcing paths the widget checks (top-level
// `regime` and `strategy_params.regime_type`).
const REALISTIC_BARE_ARRAY: RegimeTradeRecord[] = [
  {
    trade_id: "t-1",
    symbol: "MES",
    side: "BUY",
    pnl: 125.5,
    status: "CLOSED",
    strategy_params: { regime_type: "trending_bull" },
  },
  {
    trade_id: "t-2",
    symbol: "MES",
    side: "SELL",
    pnl: -42.25,
    status: "CLOSED",
    strategy_params: { regime_type: "trending_bull" },
  },
  {
    trade_id: "t-3",
    symbol: "MGC",
    side: "BUY",
    pnl: 88.0,
    status: "CLOSED",
    regime: "ranging",
  },
];

test("bare array response (the actual /portfolio/history/trades shape) — GT-28 repro", () => {
  const result = parseTradesHistoryResponse(REALISTIC_BARE_ARRAY);
  assert.equal(result.length, 3);
  assert.deepEqual(result, REALISTIC_BARE_ARRAY);
});

test("empty bare array", () => {
  assert.deepEqual(parseTradesHistoryResponse([]), []);
});

test("wrapper shape ({trades: [...]}) still parses correctly", () => {
  const result = parseTradesHistoryResponse({ trades: REALISTIC_BARE_ARRAY, count: 3 });
  assert.equal(result.length, 3);
});

test("wrapper shape with missing trades key falls back to []", () => {
  assert.deepEqual(parseTradesHistoryResponse({ count: 0 }), []);
});

test("null/undefined payload", () => {
  assert.deepEqual(parseTradesHistoryResponse(null), []);
  assert.deepEqual(parseTradesHistoryResponse(undefined), []);
});

test("malformed non-array, non-object-with-trades payload", () => {
  assert.deepEqual(parseTradesHistoryResponse({ error: "db down" } as never), []);
});

// ── Pre-fix behavior documentation ──────────────────────────────────────────
// The pre-fix widget code was: `json.trades ?? []` applied directly to the
// fetch response. Simulate that against the real bare-array shape to prove
// the bug: destructuring `.trades` off an array is `undefined`, not the
// array's elements, so the widget always fell through to `[]`.
test("pre-fix repro: naive `.trades` destructuring off a bare array yields undefined, not the trades", () => {
  const naiveResult = (REALISTIC_BARE_ARRAY as unknown as { trades?: RegimeTradeRecord[] }).trades;
  assert.equal(naiveResult, undefined);
  // ...which is exactly why the widget rendered an empty breakdown despite
  // 3 real closed trades being present in the response.
  assert.equal((naiveResult ?? []).length, 0);
});
