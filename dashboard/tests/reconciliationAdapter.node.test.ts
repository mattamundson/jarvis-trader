import assert from "node:assert/strict";
import test from "node:test";

import {
  adaptBrokerPositionsReconciliation,
  type BrokerPositionsResponse,
} from "../lib/reconciliation.ts";

function basePayload(overrides: Partial<BrokerPositionsResponse> = {}): BrokerPositionsResponse {
  return {
    ibkr: { connected: true, positions: [] },
    schwab: { connected: false, positions: [] },
    paper: { positions: [] },
    reconciliation: {
      discrepancies: [],
      health: "ok",
      ibkr_queryable: true,
      schwab_queryable: false,
      last_checked: "2026-08-16T00:00:00Z",
    },
    ...overrides,
  };
}

test("paper_unverified remains unverified, not confirmed paper-only", () => {
  const result = adaptBrokerPositionsReconciliation(
    basePayload({
      paper: {
        positions: [
          {
            trade_id: "paper-1",
            symbol: "SPY",
            direction: "LONG",
            quantity: 1,
            entry_price: 758,
            entry_time: "2026-08-03T00:00:00Z",
          },
        ],
      },
      reconciliation: {
        discrepancies: [
          {
            symbol: "SPY",
            type: "paper_unverified",
            broker_family: "schwab",
            detail: "SCHWAB_READY=false; Schwab equities/options broker verification is intentionally dormant until Phase 3 approval. Absence is not confirmed.",
          },
        ],
        health: "partial",
        ibkr_queryable: true,
        schwab_queryable: false,
        last_checked: "2026-08-16T00:00:00Z",
      },
    })
  );

  assert.equal(result.status, "unverified");
  assert.deepEqual(result.paper_only, []);
  assert.deepEqual(result.paper_unverified, [
    {
      symbol: "SPY",
      quantity: 1,
      broker_family: "schwab",
      detail: "SCHWAB_READY=false; Schwab equities/options broker verification is intentionally dormant until Phase 3 approval. Absence is not confirmed.",
    },
  ]);
});

test("confirmed paper_only still renders as partial", () => {
  const result = adaptBrokerPositionsReconciliation(
    basePayload({
      paper: {
        positions: [
          {
            trade_id: "paper-2",
            symbol: "MES",
            direction: "LONG",
            quantity: 4,
            entry_price: 6000,
            entry_time: "2026-08-03T00:00:00Z",
          },
        ],
      },
      reconciliation: {
        discrepancies: [
          {
            symbol: "MES",
            type: "paper_only",
            broker_family: "ibkr",
            detail: "IBKR queryable and live position absent.",
          },
        ],
        health: "partial",
        ibkr_queryable: true,
        schwab_queryable: false,
        last_checked: "2026-08-16T00:00:00Z",
      },
    })
  );

  assert.equal(result.status, "partial");
  assert.deepEqual(result.paper_unverified, []);
  assert.deepEqual(result.paper_only, [{ symbol: "MES", quantity: 4 }]);
});
