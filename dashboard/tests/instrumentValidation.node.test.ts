// Regression test for the Instrument Validation Scorecard's row-building logic.
//
// WHY (CLAUDE.md "Verification discipline" + dashboard-honesty class of bug):
// the widget used to hardcode MCL and MNQ as permanently "APPROVED... approved
// and trading" regardless of what the live /paper/validation/approved-paper-gates
// endpoint returned -- the endpoint only ever returns APPROVED_PAPER_SYMBOLS
// (MES, MGC), so MCL/MNQ (both in engine/backtest/signals.py's
// DO_NOT_TRADE_SYMBOLS) always fell through to a fabricated "APPROVED" fallback,
// while MGC's real live data was silently dropped and MES was faked as a static
// "Revalidating" row. buildInstrumentValidationRows() now derives every row
// straight from the API response with no symbol hardcoded in either direction.
//
// Run: cd dashboard && pnpm run test:unit

import { test } from "node:test";
import assert from "node:assert/strict";
import { buildInstrumentValidationRows } from "../lib/instrumentValidation.ts";
import type { ApprovedPaperGatesResponse } from "../lib/api.ts";

function gate(name: string, current: number, target: number, passes: boolean) {
  return { name, current, target, passes, unit: "" };
}

test("buildInstrumentValidationRows: empty/undefined data yields no rows", () => {
  assert.deepEqual(buildInstrumentValidationRows(undefined), []);
  assert.deepEqual(
    buildInstrumentValidationRows({
      status: "ok",
      thresholds: {},
      instruments: [],
      note: "",
    }),
    [],
  );
});

test("buildInstrumentValidationRows: rows are derived from live instruments only, never a hardcoded MCL/MNQ list", () => {
  const data: ApprovedPaperGatesResponse = {
    status: "ok",
    thresholds: {},
    note: "",
    instruments: [
      {
        symbol: "MES",
        trade_count: 12,
        days_with_trades: 5,
        overall_pass: true,
        gates: [
          gate("profit_factor", 2.1, 2.0, true),
          gate("sharpe_ratio", 1.6, 1.5, true),
          gate("win_rate", 58.3, 50, true),
        ],
      },
      {
        symbol: "MGC",
        trade_count: 3,
        days_with_trades: 2,
        overall_pass: false,
        gates: [
          gate("profit_factor", 0.8, 2.0, false),
          gate("sharpe_ratio", -0.2, 1.5, false),
          gate("win_rate", 33.3, 50, false),
        ],
      },
    ],
  };

  const rows = buildInstrumentValidationRows(data);
  assert.deepEqual(
    rows.map((r) => r.symbol),
    ["MES", "MGC"],
  );

  const mes = rows[0];
  assert.equal(mes.status, "APPROVED");
  assert.equal(mes.badgeVariant, "bull");
  assert.equal(mes.pf, 2.1);
  assert.equal(mes.sharpe, 1.6);
  // win_rate gate values from the API are already 0-100 scale -- must be
  // passed through as-is, not multiplied by 100 again.
  assert.equal(mes.wr, 58.3);

  const mgc = rows[1];
  assert.equal(mgc.status, "REVIEWING");
  assert.equal(mgc.badgeVariant, "info");
  assert.equal(mgc.pf, 0.8);

  // Neither halted instrument (MCL/MNQ) appears anywhere, and nothing is
  // fabricated for a symbol the API didn't report.
  assert.ok(!rows.some((r) => r.symbol === "MCL"));
  assert.ok(!rows.some((r) => r.symbol === "MNQ"));
});

test("buildInstrumentValidationRows: missing gates surface as null, not a fabricated number", () => {
  const data: ApprovedPaperGatesResponse = {
    status: "ok",
    thresholds: {},
    note: "",
    instruments: [
      {
        symbol: "MES",
        trade_count: 0,
        days_with_trades: 0,
        overall_pass: false,
        gates: [],
      },
    ],
  };

  const [row] = buildInstrumentValidationRows(data);
  assert.equal(row.pf, null);
  assert.equal(row.sharpe, null);
  assert.equal(row.wr, null);
  assert.equal(row.status, "REVIEWING");
});
