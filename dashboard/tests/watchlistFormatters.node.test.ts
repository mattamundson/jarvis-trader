/**
 * GT-18 regression: /watchlist "24h Change" column was rendering
 * change_pct ~100x too large (e.g. a real +0.07% move on MES displayed as
 * "+7.05%") because formatChangePct() multiplied by 100 a value the engine
 * already returns percent-scaled. Same pattern precedent as
 * tests/position-sizing.test.ts — real execution via Node's built-in test
 * runner, not a type-shape-only compile check.
 *
 * Run via: node --test --experimental-strip-types \
 *   --import ./tests/_register-alias.mjs tests/watchlistFormatters.node.test.ts
 * (or `pnpm run test:unit`, which globs tests/**\/*.node.test.ts)
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { formatChangePct, formatPrice } from "../lib/watchlistFormatters.ts";

test("formatChangePct: known live values from the GT-18 report render at their true magnitude", () => {
  // Raw engine values pulled directly from the GT-18 backlog evidence
  // (GET /watchlist on 2026-07-24): each is already percent-scaled.
  assert.equal(formatChangePct(0.0705171), "+0.07%"); // MES: was rendering "+7.05%"
  assert.equal(formatChangePct(-0.0405872), "-0.04%"); // SPY: was rendering "-4.06%"
  assert.equal(formatChangePct(-0.0520427), "-0.05%"); // QQQ: was rendering "-5.20%"
  assert.equal(formatChangePct(-0.233093), "-0.23%"); // TSLA: was rendering "-23.31%"
});

test("formatChangePct: does not re-scale — output equals input to 2dp with a sign", () => {
  assert.equal(formatChangePct(1.5), "+1.50%");
  assert.equal(formatChangePct(-2.25), "-2.25%");
  assert.equal(formatChangePct(0), "+0.00%");
});

test("formatChangePct: null renders the em-dash placeholder, never '0%' or NaN", () => {
  assert.equal(formatChangePct(null), "—");
});

test("formatPrice: known live values from the GT-17 report render correctly", () => {
  // Corrected AAPL close from the GT-17 report (CSV + live web quote agreed).
  assert.equal(formatPrice(325.89), "325.89");
  // >= 1000 path (thousands separator branch) — MES-scale futures price.
  assert.equal(formatPrice(7494.1), "7,494.10");
});

test("formatPrice: null renders the em-dash placeholder", () => {
  assert.equal(formatPrice(null), "—");
});
