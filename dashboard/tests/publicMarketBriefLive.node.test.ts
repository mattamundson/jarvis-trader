import assert from "node:assert/strict";
import { test } from "node:test";

import { __test__ } from "@/lib/marketBrief/live";

test("live public generator outcome partition matches market brief scoring contract", () => {
  assert.equal(__test__.labelPartition(101, 99, 100, 98), "continuation");
  assert.equal(__test__.labelPartition(99, 97, 100, 98), "failure");
  assert.equal(__test__.labelPartition(99, 98.5, 100, 98), "rotation");
});

test("live public generator rates round to exactly 100.0", () => {
  const rates = __test__.exactRates({ continuation: 1, rotation: 1, failure: 1 }, 3);
  assert.equal(Number((rates.continuation + rates.rotation + rates.failure).toFixed(1)), 100.0);
});

test("live public generator keeps state conditioning diagnostic labels explicit", () => {
  assert.equal(__test__.classifyState(false, 15, 3), "not_ath_close");
  assert.equal(__test__.classifyState(true, 15, 3), "ath_close_lowvol_accel_gt2");
  assert.equal(__test__.classifyState(true, 18, 3), "ath_close_hivol");
});
