// Regression test for D2-03-v2 (2026-07-24 dashboard-integrity audit,
// follow-up to D2-03/scorecard-baseline-active-pair.node.test.ts).
//
// D2-03's lib-level fix (PREFERRED_BASELINE_SYMBOL_SUBSTRINGS derived from
// DEFAULT_BRIEFING_SYMBOLS) never propagated to five components that had
// their OWN independent hardcoded MCL/MNQ text/logic:
//   - BacktestVsPaperWidget.tsx ("MCL/MNQ preferred" label)
//   - app/validation/page.tsx ("No MCL/MNQ baseline JSON" etc. + a
//     SimulateTradePanel `SYMBOLS`/default-selector defaulting to "MCL")
//   - app/scorecard/page.tsx ("MCL/MNQ preferred" labels)
//   - components/InstrumentValidationScorecard.tsx (a *factual* bug: it
//     hardcoded MCL/MNQ as APPROVED-and-trading with static WFE 0.82/0.57,
//     and MES as "Revalidating" — the exact opposite of engine reality)
//   - PaperApprovedValidationWidget.tsx ("Paper validation — MCL & MNQ")
//
// This test covers the two files that gained real (non-JSX) pure logic as
// part of that fix: lib/approvedSymbols.ts's new exports, and the extracted
// lib/instrumentValidationRows.ts row-builder. The text-only fixes in the
// three page/widget files are pure JSX string interpolation off of these
// same constants — see the commit body for why they have no separate
// exported pure logic to unit test.
//
// Run: cd dashboard && pnpm run test:unit

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_BRIEFING_SYMBOLS,
  HALTED_SYMBOLS,
  ALL_TRACKED_SYMBOLS,
  PREFERRED_BASELINE_LABEL,
  INSTRUMENT_STATUS,
} from "../lib/approvedSymbols.ts";
import {
  buildInstrumentRow,
  buildDefaultInstrumentRows,
} from "../lib/instrumentValidationRows.ts";
import type { ApprovedInstrumentGateRow } from "../lib/api.ts";

// ── approvedSymbols.ts additions ────────────────────────────────────────────

test("PREFERRED_BASELINE_LABEL renders the active pair, not the halted one", () => {
  assert.equal(PREFERRED_BASELINE_LABEL, "MES/MGC");
});

test("HALTED_SYMBOLS never overlaps DEFAULT_BRIEFING_SYMBOLS", () => {
  for (const sym of HALTED_SYMBOLS) {
    assert.ok(
      !(DEFAULT_BRIEFING_SYMBOLS as readonly string[]).includes(sym),
      `HALTED_SYMBOLS must not include an actively-traded symbol, found "${sym}"`
    );
  }
  assert.deepEqual([...HALTED_SYMBOLS].sort(), ["MCL", "MNQ"]);
});

test("ALL_TRACKED_SYMBOLS is the active pair followed by the halted pair, no duplicates", () => {
  assert.deepEqual([...ALL_TRACKED_SYMBOLS], ["MES", "MGC", "MCL", "MNQ"]);
  assert.equal(new Set(ALL_TRACKED_SYMBOLS).size, ALL_TRACKED_SYMBOLS.length);
});

test("INSTRUMENT_STATUS marks the active pair APPROVED and the halted pair HALTED", () => {
  for (const sym of DEFAULT_BRIEFING_SYMBOLS) {
    assert.equal(
      INSTRUMENT_STATUS[sym].status,
      "APPROVED",
      `${sym} is in DEFAULT_BRIEFING_SYMBOLS and must read APPROVED`
    );
  }
  for (const sym of HALTED_SYMBOLS) {
    assert.equal(
      INSTRUMENT_STATUS[sym].status,
      "HALTED",
      `${sym} is in HALTED_SYMBOLS and must read HALTED`
    );
  }
});

// ── instrumentValidationRows.ts (extracted from InstrumentValidationScorecard.tsx) ─

function gateRow(symbol: string, overallPass: boolean): ApprovedInstrumentGateRow {
  return {
    symbol,
    overall_pass: overallPass,
    trade_count: 12,
    days_with_trades: 5,
    gates: [
      { name: "profit_factor", current: 1.8, target: 2, unit: "", passes: overallPass },
      { name: "sharpe_ratio", current: 1.2, target: 1.5, unit: "", passes: overallPass },
      { name: "win_rate", current: 52, target: 55, unit: "%", passes: overallPass },
    ],
  };
}

test("buildInstrumentRow: halted symbols always read HALTED, even if the live endpoint returns a passing row for them", () => {
  // Reproduces the exact pre-fix bug shape: engine returns MCL/MNQ rows that
  // look like they pass gates. Pre-fix, the component read this as
  // "MCL/MNQ are APPROVED and trading". Post-fix it must still say HALTED —
  // halted status is a static engine routing fact, not something a paper
  // gate result can override.
  const map = new Map<string, ApprovedInstrumentGateRow>([
    ["MCL", gateRow("MCL", true)],
    ["MNQ", gateRow("MNQ", true)],
  ]);
  for (const sym of HALTED_SYMBOLS) {
    const row = buildInstrumentRow(sym, map);
    assert.equal(row.status, "HALTED", `${sym} must read HALTED regardless of live gate data`);
    assert.equal(row.badgeVariant, "bear");
    assert.equal(row.pf, null, `${sym} must not surface live PF/Sharpe/WR — it isn't traded`);
  }
});

test("buildInstrumentRow: active pair reads APPROVED by default and reflects live overall_pass when present", () => {
  const empty = new Map<string, ApprovedInstrumentGateRow>();
  for (const sym of DEFAULT_BRIEFING_SYMBOLS) {
    const row = buildInstrumentRow(sym, empty);
    assert.equal(row.status, "APPROVED");
    assert.equal(row.badgeVariant, "bull");
  }

  const failing = new Map<string, ApprovedInstrumentGateRow>([
    ["MES", gateRow("MES", false)],
  ]);
  const mesRow = buildInstrumentRow("MES", failing);
  assert.equal(mesRow.status, "REVIEWING");
  assert.equal(mesRow.badgeVariant, "info");
  assert.equal(mesRow.pf, 1.8, "live gate data should populate PF for the active pair");
});

test("buildDefaultInstrumentRows never labels MCL/MNQ as approved-and-trading (the D2-03-v2 factual bug)", () => {
  const rows = buildDefaultInstrumentRows();
  const bySymbol = new Map(rows.map((r) => [r.symbol, r]));

  for (const sym of HALTED_SYMBOLS) {
    assert.equal(bySymbol.get(sym)?.status, "HALTED");
  }
  for (const sym of DEFAULT_BRIEFING_SYMBOLS) {
    assert.notEqual(bySymbol.get(sym)?.status, "HALTED");
  }
  // The original bug also pinned static WFE 0.82 (MCL) / 0.57 (MNQ) as if
  // those were passing walk-forward-efficiency scores. Halted symbols must
  // report the true 0.00.
  for (const sym of HALTED_SYMBOLS) {
    assert.equal(bySymbol.get(sym)?.wfe, "0.00");
  }
});
