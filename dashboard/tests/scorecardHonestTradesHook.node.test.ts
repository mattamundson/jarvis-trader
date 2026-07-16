// Hook-consumer-parity regression test for the scorecard page's honest-trades
// subscription (Bug B / T2-18, 2026-07-11 dashboard audit).
//
// WHY: scorecard/page.tsx used to open its own standalone `useSWR("scorecard/
// honest-trades", fetchHonestTrades, ...)` subscription instead of the shared
// `useHonestTrades()` hook every other widget on the page consumes. SWR keys
// its cache by the literal key string, so the duplicate subscription never
// shared state with the already-warm shared cache and could independently
// fail/return empty — that's the root cause of Trade Summary rendering
// $0.00 / 0 trades while the rest of the page showed real data.
//
// There's no jsdom/React-renderer in this project's test infra (see
// package.json test:unit — plain `node --test` over "tests/**/*.node.test.ts"),
// so this is a source-level parity check rather than a rendered-DOM
// assertion: it locks the page's *code path* to the shared hook so a future
// edit can't silently reintroduce a standalone SWR subscription to the same
// endpoint under a different key.
//
// Run: cd dashboard && pnpm run test:unit

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const pageSrc = readFileSync(
  path.join(here, "..", "app", "scorecard", "page.tsx"),
  "utf8",
);

test("scorecard page imports the shared useHonestTrades hook", () => {
  assert.match(
    pageSrc,
    /import\s*\{\s*useHonestTrades\s*\}\s*from\s*["']@\/lib\/useHonestTrades["']/,
    "scorecard/page.tsx must import useHonestTrades from @/lib/useHonestTrades",
  );
});

test("scorecard page calls useHonestTrades() to source its honest trade record", () => {
  assert.match(
    pageSrc,
    /=\s*useHonestTrades\(/,
    "scorecard/page.tsx must call useHonestTrades(...) to populate the honest trade record",
  );
});

test("scorecard page does not re-open a standalone SWR subscription to the honest-trades endpoint", () => {
  // The old bug: a second, independently-keyed useSWR(...) call to
  // fetchHonestTrades. Any reintroduction of the old key or a direct
  // fetchHonestTrades import (bypassing the shared hook) should fail this test.
  assert.doesNotMatch(
    pageSrc,
    /["']scorecard\/honest-trades["']/,
    "scorecard/page.tsx must not use the old standalone \"scorecard/honest-trades\" SWR key",
  );
  assert.doesNotMatch(
    pageSrc,
    /\bfetchHonestTrades\b/,
    "scorecard/page.tsx must not import/call fetchHonestTrades directly — use the shared useHonestTrades() hook instead",
  );
});

test("Trade Summary widget's trade-count/win/loss values derive from the shared hook's honest set", () => {
  // Guards the wiring, not just the import: totalTrades/wins/losses (rendered
  // in the Trade Summary section) must be derived from `honestSet`, which is
  // itself destructured from useHonestTrades()'s return value.
  assert.match(
    pageSrc,
    /honest:\s*honestSet[\s\S]{0,200}=\s*useHonestTrades\(/,
    "honestSet must be destructured (as `honest: honestSet`) from useHonestTrades()'s return shape",
  );
  assert.match(
    pageSrc,
    /const\s+totalTrades\s*=\s*honestSet\?\.\s*trades\.length/,
    "totalTrades must derive from honestSet.trades.length",
  );
  assert.match(
    pageSrc,
    /const\s+wins\s*=\s*honestSet\?\.\s*wins/,
    "wins must derive from honestSet.wins",
  );
  assert.match(
    pageSrc,
    /const\s+losses\s*=\s*honestSet\?\.\s*losses/,
    "losses must derive from honestSet.losses",
  );
});
