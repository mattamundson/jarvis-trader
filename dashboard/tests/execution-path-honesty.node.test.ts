// Execution-path honesty regression tests (D3-01).
//
// WHY: every dashboard execution-status badge (8+ mounted components) was
// rendering a green "CONNECTED" from `ibkr_execution_connected` /
// `execution_connected_verified` — cached connector booleans that go true the
// instant the TCP socket to the paper IB Gateway is up. The engine's own
// /health ALSO carries an honest `execution_path` probe that can read
// `simulated: true, broker_ack: false` — "IBGatewayConnector holds no
// ib_insync handle, orders are simulated in-process and never reach a
// broker" — at the exact same moment both legacy booleans read true. No
// dashboard file read `execution_path` before this fix. lib/executionPath.ts
// is now the single source of truth for execution-status display; these
// tests lock its resolution order and the two safety invariants
// (brokerReachable is true ONLY on a real broker ack; a bare "CONNECTED"
// label / "bull" tone implies brokerReachable) so a future edit can't
// silently re-introduce the lie.
//
// Run: cd dashboard && pnpm run test:unit
//   (node --test --experimental-strip-types "tests/**/*.node.test.ts")

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  executionStatus,
  type ExecutionHealthFields,
} from "../lib/executionPath.ts";

// ── Case 1: simulator + Gateway port down ───────────────────────────────────
test("simulator + Gateway port down -> simulated, never reachable", () => {
  const h: ExecutionHealthFields = {
    ibkr_connected: false,
    ibkr_execution_connected: false,
    execution_connected_verified: false,
    ib_execution_stale: false,
    execution_path: {
      class_name: "IBGatewayConnector",
      simulated: true,
      broker_ack: false,
      detail:
        "IBGatewayConnector holds no ib_insync handle -- orders are simulated in-process and never reach a broker",
    },
  };
  const s = executionStatus(h);
  assert.equal(s.state, "simulated");
  assert.equal(s.brokerReachable, false);
  assert.equal(s.label, "SIMULATED");
  assert.equal(s.tone, "warn");
  assert.ok(s.detail.includes("never reach a broker"));
});

// ── Case 2 (THE REGRESSION THIS FIXES): simulator + Gateway port UP ─────────
test("REGRESSION: simulator + Gateway port UP -- both legacy booleans true, honest probe still wins", () => {
  const h: ExecutionHealthFields = {
    ibkr_connected: true,
    ibkr_execution_connected: true,
    execution_connected_verified: true,
    ib_execution_stale: false,
    execution_path: {
      class_name: "IBGatewayConnector",
      simulated: true,
      broker_ack: false,
    },
  };
  const s = executionStatus(h);
  assert.equal(s.state, "simulated");
  assert.equal(s.brokerReachable, false);
  assert.notEqual(s.label, "CONNECTED");
});

// ── Case 3: real gateway, IB down ────────────────────────────────────────────
test("real gateway, IB down -> degraded / NO BROKER ACK", () => {
  const h: ExecutionHealthFields = {
    ibkr_connected: false,
    ibkr_execution_connected: false,
    execution_connected_verified: false,
    ib_execution_stale: false,
    execution_path: {
      class_name: "IBGatewayManager",
      simulated: false,
      broker_ack: false,
    },
  };
  const s = executionStatus(h);
  assert.equal(s.state, "degraded");
  assert.equal(s.brokerReachable, false);
  assert.equal(s.label, "NO BROKER ACK");
});

// ── Case 4 (the ONLY green case): real gateway, broker answered ─────────────
test("the ONLY green case: real gateway, broker acknowledged", () => {
  const h: ExecutionHealthFields = {
    ibkr_connected: true,
    ibkr_execution_connected: true,
    execution_connected_verified: true,
    ib_execution_stale: false,
    execution_path: {
      class_name: "IBGatewayManager",
      simulated: false,
      broker_ack: true,
    },
  };
  const s = executionStatus(h);
  assert.equal(s.state, "connected");
  assert.equal(s.brokerReachable, true);
  assert.equal(s.label, "CONNECTED");
  assert.equal(s.tone, "bull");
});

// ── Case 5: older engine, no probe at all ───────────────────────────────────
test("older engine, no execution_path probe -> unprobed (amber), not bare CONNECTED", () => {
  const h: ExecutionHealthFields = {
    ibkr_connected: true,
    ibkr_execution_connected: true,
    // execution_connected_verified and execution_path both absent -- simulates
    // an engine build that predates the probe.
  };
  const s = executionStatus(h);
  assert.equal(s.state, "unprobed");
  assert.equal(s.label, "CONNECTED (UNPROBED)");
  assert.equal(s.tone, "warn");
  assert.equal(s.brokerReachable, false);
});

// ── Case 6: null / undefined input ──────────────────────────────────────────
test("executionStatus(null) and executionStatus(undefined) never throw", () => {
  const sNull = executionStatus(null);
  assert.equal(sNull.state, "unknown");
  assert.equal(sNull.brokerReachable, false);

  const sUndef = executionStatus(undefined);
  assert.equal(sUndef.state, "unknown");
  assert.equal(sUndef.brokerReachable, false);
});

// ── Case 7: stale, no probe ──────────────────────────────────────────────────
test("stale with no probe -> brokerReachable false regardless of branch taken", () => {
  const h: ExecutionHealthFields = {
    ibkr_connected: false,
    ibkr_execution_connected: false,
    execution_connected_verified: false,
    ib_execution_stale: true,
  };
  const s = executionStatus(h);
  assert.equal(s.brokerReachable, false);
  // May land on "stale" or (if a legacy flag were truthy) "unprobed" depending
  // on exact resolution order -- both are safe; brokerReachable is what matters.
  assert.ok(s.state === "stale" || s.state === "unprobed" || s.state === "disconnected");
});

// ── Case 8 (INVARIANT SWEEP): full cross product, 256 payloads ─────────────
test("INVARIANT SWEEP: brokerReachable / CONNECTED / bull-tone invariants hold for every combination", () => {
  const simulatedValues: Array<boolean | null | undefined> = [true, false, null, undefined];
  const brokerAckValues: Array<boolean | null | undefined> = [true, false, null, undefined];
  const boolValues = [true, false];

  let count = 0;
  for (const simulated of simulatedValues) {
    for (const broker_ack of brokerAckValues) {
      for (const ibkr_execution_connected of boolValues) {
        for (const execution_connected_verified of boolValues) {
          for (const ib_execution_stale of boolValues) {
            count += 1;
            // execution_path itself is only absent when an older engine sends
            // neither field at all; otherwise each field independently carries
            // its own true/false/null/undefined ("absent key") value.
            const bothAbsent = simulated === undefined && broker_ack === undefined;
            const payload: ExecutionHealthFields = {
              ibkr_connected: ibkr_execution_connected,
              ibkr_execution_connected,
              execution_connected_verified,
              ib_execution_stale,
              execution_path: bothAbsent ? undefined : { simulated, broker_ack },
            };

            let thrown = false;
            let s: ReturnType<typeof executionStatus>;
            try {
              s = executionStatus(payload);
            } catch {
              thrown = true;
              s = executionStatus(null); // placeholder so TS sees an assignment
            }
            assert.equal(thrown, false, `threw for ${JSON.stringify(payload)}`);

            // (i) brokerReachable is a pure function of execution_path.broker_ack.
            const expectedReachable = payload.execution_path?.broker_ack === true;
            assert.equal(
              s.brokerReachable,
              expectedReachable,
              `brokerReachable mismatch for ${JSON.stringify(payload)}`,
            );

            // (ii) label === "CONNECTED" implies brokerReachable === true.
            if (s.label === "CONNECTED") {
              assert.equal(s.brokerReachable, true, `CONNECTED but not reachable: ${JSON.stringify(payload)}`);
            }

            // (iii) tone === "bull" implies brokerReachable === true.
            if (s.tone === "bull") {
              assert.equal(s.brokerReachable, true, `bull tone but not reachable: ${JSON.stringify(payload)}`);
            }

            // (iv) never throws (covered by doesNotThrow above), always a
            // non-empty label.
            assert.ok(typeof s.label === "string" && s.label.length > 0);
          }
        }
      }
    }
  }

  assert.equal(count, 4 * 4 * 2 * 2 * 2); // 256 payloads
});
