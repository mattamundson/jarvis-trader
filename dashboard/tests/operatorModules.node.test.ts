import test from "node:test";
import assert from "node:assert/strict";
import { bookDisagreements } from "@/lib/bookDisagreement";
import { scoreboardRejectsMethod, isVercelDeployment } from "@/lib/operatorMode";
import { unavailableHermesGates } from "@/lib/hermesGates";
import { readFileSync } from "node:fs";

test("operator proxy rejects all write and unknown methods", () => {
  for (const method of ["POST", "PUT", "PATCH", "DELETE", "post", "TRACE", "UNKNOWN"]) {
    assert.equal(scoreboardRejectsMethod(method), true);
  }
  for (const method of ["GET", "HEAD", "OPTIONS"]) {
    assert.equal(scoreboardRejectsMethod(method), false);
  }
});

test("deployment detection uses VERCEL=1 only", () => {
  const previous = process.env.VERCEL;
  try {
    for (const value of ["1", "0", "true", ""]) {
      process.env.VERCEL = value;
      assert.equal(isVercelDeployment(), value === "1");
    }
  } finally {
    if (previous === undefined) delete process.env.VERCEL;
    else process.env.VERCEL = previous;
  }
});

test("book comparison aggregates quantities and detects missing and invalid rows", () => {
  const line = (quantity: number) => ({ symbol: "MES", quantity });
  assert.deepEqual(bookDisagreements([line(1), line(2)], [line(3)]), []);
  assert.deepEqual(bookDisagreements([], []), []);
  assert.deepEqual(bookDisagreements([line(2)], [line(1)]), ["MES: /portfolio qty 2; paper qty 1"]);
  assert.deepEqual(bookDisagreements([], [line(1)]), ["MES: /portfolio qty 0; paper qty 1"]);
  assert.deepEqual(bookDisagreements([line(NaN)], []), ["MES: quantity unavailable"]);
});

test("absent gates never claim pass or unlocked", () => {
  const report = unavailableHermesGates();
  assert.equal(report.found, false);
  assert.deepEqual(report.gates, []);
  assert.equal(report.fileLockout, null);
  assert.match(report.message, /unavailable/);
});

test("hosted component does not import local scoreboard or trading panels", () => {
  const source = readFileSync(new URL("../app/mission-control/VercelGatesOnly.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /OperatorScoreboard|MissionControlLocal|TradeExecution|PositionsPerformance|PnL/);
});
