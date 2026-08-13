import { test } from "node:test";
import assert from "node:assert/strict";
import {
  APPROVALS_KEY,
  EXECUTION_STATE_KEY,
  HEALTH_KEY,
  POLL_INTERVAL,
  POSITIONS_KEY,
  pollingIntervalForMs,
} from "../lib/polling-config.ts";

test("existing cadences map without becoming faster", () => {
  assert.equal(pollingIntervalForMs(5_000), POLL_INTERVAL.FAST);
  assert.equal(pollingIntervalForMs(15_000), POLL_INTERVAL.STATUS);
  assert.equal(pollingIntervalForMs(60_000), POLL_INTERVAL.MINUTE);
  assert.equal(pollingIntervalForMs(120_000), POLL_INTERVAL.TWO_MINUTES);
  assert.equal(pollingIntervalForMs(300_000), POLL_INTERVAL.FIVE_MINUTES);
});

test("specialized existing cadences retain exact values", () => {
  assert.equal(pollingIntervalForMs(2_000), POLL_INTERVAL.REALTIME);
  assert.equal(pollingIntervalForMs(3_000), POLL_INTERVAL.APPROVALS);
  assert.equal(pollingIntervalForMs(30 * 60_000), POLL_INTERVAL.HALF_HOUR);
});

test("unknown cadences fail instead of silently polling faster", () => {
  assert.throws(() => pollingIntervalForMs(7_000), /Unmapped polling interval/);
});

test("canonical operational keys remain centralized", () => {
  assert.equal(HEALTH_KEY, "/health");
  assert.equal(POSITIONS_KEY, "/brokers/positions");
  assert.equal(APPROVALS_KEY, "/pipeline/pending-approvals");
  assert.equal(EXECUTION_STATE_KEY, "/safety/status");
});
