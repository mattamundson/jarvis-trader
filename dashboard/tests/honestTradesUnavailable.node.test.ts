// Behavioral regression test for GT-06 (dashboard-integrity backlog).
//
// WHY: /scorecard's Key Metrics tiles (Total P&L, Profit Factor, Win Rate)
// were rendering $0.00 / 0.00 / 0.0% in FAIL/red styling whenever
// fetchHonestTrades() threw (root cause: master-api, a separate service on
// :8030, unreachable — see AGENTS.md "External service: master-api" and
// dashboard/lib/masterApi.ts fetchRealizedPnl / dashboard/lib/honestTrades.ts
// fetchHonestTrades). The throw itself is CORRECT, honest behavior — the bug
// was entirely downstream: every consumer fell back to `?? 0` and fed that
// fabricated zero into color-scored gate logic, which painted "we don't know"
// as "the strategy is failing".
//
// isHonestUnavailable() is the single pure decision function that now gates
// every honest-derived display on scorecard/page.tsx. Unlike the
// source-level parity checks below (this repo has no jsdom/React renderer —
// see scorecardHonestTradesHook.node.test.ts), this is a REAL behavioral
// test: it imports and calls the actual function with the actual
// HonestTradeSet shape and asserts on its actual return value.
//
// Run: cd dashboard && pnpm run test:unit

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { isHonestUnavailable, type HonestTradeSet } from "@/lib/honestTrades";

const here = path.dirname(fileURLToPath(import.meta.url));

function makeSet(overrides: Partial<HonestTradeSet> = {}): HonestTradeSet {
  return {
    trades: [],
    net: 5537.51,
    wins: 12,
    losses: 21,
    winRate: 0.365,
    profitFactor: 2.2,
    grossWin: 9000,
    grossLoss: 3462.49,
    headline: "ok",
    rawRows: 33,
    relogged: 0,
    caveats: [],
    ...overrides,
  };
}

// ── isHonestUnavailable() — the three real SWR states ──────────────────────

test("isHonestUnavailable: still loading (no data yet) is NOT unavailable", () => {
  assert.equal(isHonestUnavailable(null, /* loadingHonest */ true), false);
  assert.equal(isHonestUnavailable(undefined, true), false);
});

test("isHonestUnavailable: fetchHonestTrades() threw -- settled with no data -- IS unavailable", () => {
  // This is exactly the state useHonestTrades() is in after fetchHonestTrades()
  // throws: SWR's `error` is set, `data` stays undefined, `isLoading` is false.
  assert.equal(isHonestUnavailable(null, /* loadingHonest */ false), true);
  assert.equal(isHonestUnavailable(undefined, false), true);
});

test("isHonestUnavailable: successful fetch with a real record is NOT unavailable", () => {
  assert.equal(isHonestUnavailable(makeSet(), false), false);
});

test("isHonestUnavailable: a real record with zero trades (e.g. brand-new account) is NOT unavailable", () => {
  // Guards against conflating "genuinely zero trades" with "fetch failed" --
  // both would otherwise look identical if this function keyed off net===0
  // instead of the presence of the record itself.
  assert.equal(
    isHonestUnavailable(
      makeSet({ trades: [], net: 0, wins: 0, losses: 0, winRate: 0, profitFactor: null }),
      false,
    ),
    false,
  );
});

// ── Source-level guard: scorecard/page.tsx must actually gate on it ───────
// (No renderer in this repo's test infra -- see scorecardHonestTradesHook
// .node.test.ts for the established pattern. This locks the *wiring*, not
// just the existence of the helper function.)

const pageSrc = readFileSync(
  path.join(here, "..", "app", "scorecard", "page.tsx"),
  "utf8",
);

test("scorecard page imports and computes honestUnavailable from isHonestUnavailable()", () => {
  assert.match(
    pageSrc,
    /import\s*\{[^}]*\bisHonestUnavailable\b[^}]*\}\s*from\s*["']@\/lib\/honestTrades["']/,
    "scorecard/page.tsx must import isHonestUnavailable from @/lib/honestTrades",
  );
  assert.match(
    pageSrc,
    /const\s+honestUnavailable\s*=\s*isHonestUnavailable\(/,
    "scorecard/page.tsx must derive honestUnavailable from isHonestUnavailable(...)",
  );
});

test("Key Metrics tiles (Profit Factor / Win Rate / Total P&L) branch on honestUnavailable instead of rendering a bare fallback-zero", () => {
  // Guards the exact GT-06 regression: fmt2(pf)/fmtPct(wr)/formatCurrency(totalPnl)
  // must never be the unconditional value for these three tiles again -- each
  // must be reachable only through a honestUnavailable ternary.
  assert.match(
    pageSrc,
    /label="Profit Factor"[\s\S]{0,120}value=\{honestUnavailable[\s\S]{0,40}fmt2\(pf\)/,
    "Profit Factor MetricCard must branch on honestUnavailable before rendering fmt2(pf)",
  );
  assert.match(
    pageSrc,
    /label="Win Rate"[\s\S]{0,120}value=\{honestUnavailable[\s\S]{0,40}fmtPct\(wr\)/,
    "Win Rate MetricCard must branch on honestUnavailable before rendering fmtPct(wr)",
  );
  assert.match(
    pageSrc,
    /label="Total P&L"[\s\S]{0,150}value=\{honestUnavailable[\s\S]{0,60}formatCurrency\(totalPnl\)/,
    "Total P&L MetricCard must branch on honestUnavailable before rendering formatCurrency(totalPnl)",
  );
});

test("Key Metrics tiles never paint a hard red/FAIL level purely from honestUnavailable", () => {
  // pfLvl/wrLvl are computed once, pinned to "yellow" (neutral) when
  // honestUnavailable, and reused by the tiles -- assert that pin exists so a
  // future edit can't reintroduce pfLevel(pf)/inline-red logic unconditioned
  // on honestUnavailable.
  assert.match(
    pageSrc,
    /const\s+pfLvl[^=]*=\s*honestUnavailable\s*\?\s*"yellow"/,
    "pfLvl must be pinned to \"yellow\" when honestUnavailable, not fall through to pfLevel(0) == \"red\"",
  );
  assert.match(
    pageSrc,
    /const\s+wrLvl[^=]*=\s*honestUnavailable\s*\?\s*"yellow"/,
    "wrLvl must be pinned to \"yellow\" when honestUnavailable, not fall through to a 0%-derived \"red\"",
  );
});
