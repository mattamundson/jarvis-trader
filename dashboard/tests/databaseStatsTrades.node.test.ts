// Regression test for GT-16: the /health dashboard's "Database Statistics"
// panel showed "Total Trades: 0" despite 63 real closed trades in the DB.
//
// Root cause: `GET /portfolio/history/trades` returns a bare JSON array
// (e.g. `[{...}, {...}]`), not the `{trades, count}` wrapper its sibling
// endpoints use. DatabaseStatsCard.tsx read `.count` / `.trades?.length`
// off that response -- both `undefined` on a bare array -- so the tile's
// total always fell through to 0, regardless of the true trade count.
//
// This locks in deriveTotalTradesCount's array-or-wrapper parsing so a
// regression (e.g. someone "simplifying" it back to `.count ?? .length`)
// fails a test instead of silently reintroducing the bug.
//
// Run: cd dashboard && pnpm run test:unit
//   (node --test --experimental-strip-types "tests/**/*.node.test.ts")

import { test } from "node:test";
import assert from "node:assert/strict";
import { deriveTotalTradesCount } from "../lib/databaseStatsTrades.ts";

test("bare array response (the actual /portfolio/history/trades shape) — GT-16 repro", () => {
  const trades = Array.from({ length: 63 }, (_, i) => ({ id: i, symbol: "MES" }));
  assert.equal(deriveTotalTradesCount(trades), 63);
});

test("empty bare array", () => {
  assert.equal(deriveTotalTradesCount([]), 0);
});

test("wrapper shape with explicit count", () => {
  assert.equal(deriveTotalTradesCount({ trades: [{ id: 1 }, { id: 2 }], count: 2 }), 2);
});

test("wrapper shape missing count falls back to trades.length", () => {
  assert.equal(deriveTotalTradesCount({ trades: [{ id: 1 }, { id: 2 }, { id: 3 }] }), 3);
});

test("wrapper shape with count=0 is trusted over trades.length (explicit zero, not a fallback)", () => {
  assert.equal(deriveTotalTradesCount({ trades: [], count: 0 }), 0);
});

test("null/undefined payload", () => {
  assert.equal(deriveTotalTradesCount(null), 0);
  assert.equal(deriveTotalTradesCount(undefined), 0);
});

test("malformed non-array object with neither count nor trades", () => {
  assert.equal(deriveTotalTradesCount({ error: "db down" }), 0);
});
