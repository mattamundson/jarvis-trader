import { test } from "node:test";
import assert from "node:assert/strict";
import {
  compactCount,
  deriveCommandCenterShellRegions,
  deriveCommandCenterStatusStripState,
} from "../lib/commandCenterState.ts";

test("compactCount formats only finite numbers", () => {
  assert.equal(compactCount(0), "0");
  assert.equal(compactCount(7), "7");
  assert.equal(compactCount(null), "—");
  assert.equal(compactCount(undefined), "—");
  assert.equal(compactCount(Number.NaN), "—");
});

test("status strip reports pending probes without claiming outages", () => {
  const state = deriveCommandCenterStatusStripState({
    health: undefined,
    healthErr: false,
    safety: undefined,
    safetyErr: false,
    killSwitchActive: false,
    execution: { tone: "neutral", detail: "not probed" },
    integrity: undefined,
    integrityErr: false,
    integrityReady: false,
    staleFeeds: 0,
  });

  assert.deepEqual(state.engine, {
    label: "unknown",
    detail: "health probe pending",
    tone: "unknown",
  });
  assert.deepEqual(state.broker, {
    label: "unknown",
    detail: "execution path pending",
    tone: "unknown",
  });
  assert.deepEqual(state.safety, {
    label: "unknown",
    detail: "safety probe pending",
    tone: "unknown",
  });
  assert.equal(state.data.label, "unknown");
});

test("status strip separates engine outage from unprobed broker", () => {
  const state = deriveCommandCenterStatusStripState({
    health: undefined,
    healthErr: true,
    safety: undefined,
    safetyErr: true,
    killSwitchActive: false,
    execution: { tone: "bear", detail: "socket down" },
    integrity: undefined,
    integrityErr: true,
    integrityReady: false,
    staleFeeds: 0,
  });

  assert.deepEqual(state.engine, {
    label: "offline",
    detail: "health endpoint unreachable",
    tone: "bad",
  });
  assert.deepEqual(state.broker, {
    label: "unknown",
    detail: "engine offline; broker unprobed",
    tone: "unknown",
  });
  assert.deepEqual(state.safety, {
    label: "unknown",
    detail: "safety endpoint unavailable",
    tone: "unknown",
  });
});

test("status strip maps healthy engine, verified broker, halted safety, and stale data", () => {
  const state = deriveCommandCenterStatusStripState({
    health: {
      status: "ok",
      kill_switch_active: true,
      uptime_seconds: 10,
      ibkr_connected: true,
      paper_trading: true,
      version: "fixture",
    },
    healthErr: false,
    safety: {
      daily_pnl: 0,
      equity_peak: 10000,
      drawdown_pct: 0,
      orders_last_minute: 2,
      orders_per_minute_limit: 10,
    },
    safetyErr: false,
    killSwitchActive: true,
    execution: { tone: "bull", detail: "broker ack" },
    integrity: { count: 3, sources: [{ source: "bars", status: "stale" }] },
    integrityErr: false,
    integrityReady: true,
    staleFeeds: 1,
  });

  assert.deepEqual(state.engine, {
    label: "online",
    detail: "version fixture",
    tone: "ok",
  });
  assert.deepEqual(state.broker, {
    label: "verified",
    detail: "broker ack",
    tone: "ok",
  });
  assert.deepEqual(state.safety, {
    label: "halted",
    detail: "kill switch active",
    tone: "bad",
  });
  assert.deepEqual(state.data, {
    label: "stale",
    detail: "1 stale feed",
    tone: "warn",
  });
});

test("shell regions preserve Command Center readiness semantics", () => {
  const regions = deriveCommandCenterShellRegions({
    engineOnline: true,
    killSwitchActive: false,
    paperTrading: false,
    executionLabel: "CONNECTED",
    decisionsCount: 2,
    decisionsErr: false,
    tradesCount: 4,
    tradesErr: false,
    hasPaperStatus: true,
    approvedInstruments: 3,
    totalInstruments: 4,
    haltedInstruments: 1,
    ledgerReady: true,
    ledgerErr: false,
    ledgerPassCount: 1,
    ledgerFailCount: 2,
    ledgerTotal: 3,
    integrityReady: true,
    integrityErr: false,
    integrityCount: 5,
    staleFeeds: 0,
  });

  assert.equal(regions.length, 6);
  assert.deepEqual(regions.map((region) => region.key), [
    "systemStatus",
    "tradeQueue",
    "eligibility",
    "strategyLedger",
    "dataIntegrity",
    "researchIntake",
  ]);
  assert.match(regions[0].detail, /live flag observed/);
  assert.equal(regions[0].metric, "OK");
  assert.equal(regions[1].metric, "2 recent");
  assert.equal(regions[1].detail, "4 fill rows visible");
  assert.equal(regions[2].metric, "3/4");
  assert.equal(regions[3].detail, "2 fail · 3 verdicts");
  assert.equal(regions[4].tone, "live");
  assert.equal(regions[5].tone, "static");
});

test("shell regions degrade independently when sources are unavailable", () => {
  const regions = deriveCommandCenterShellRegions({
    engineOnline: false,
    killSwitchActive: false,
    paperTrading: undefined,
    executionLabel: "EXEC ?",
    decisionsCount: undefined,
    decisionsErr: true,
    tradesCount: undefined,
    tradesErr: true,
    hasPaperStatus: false,
    approvedInstruments: 0,
    totalInstruments: 4,
    haltedInstruments: 4,
    ledgerReady: false,
    ledgerErr: true,
    ledgerPassCount: undefined,
    ledgerFailCount: undefined,
    ledgerTotal: undefined,
    integrityReady: false,
    integrityErr: true,
    integrityCount: undefined,
    staleFeeds: 0,
  });

  const byKey = Object.fromEntries(regions.map((region) => [region.key, region]));
  assert.equal(byKey.systemStatus.status, "offline");
  assert.equal(byKey.systemStatus.metric, "DOWN");
  assert.equal(byKey.tradeQueue.status, "degraded");
  assert.equal(byKey.tradeQueue.detail, "fills unavailable");
  assert.equal(byKey.eligibility.status, "fallback");
  assert.equal(byKey.strategyLedger.status, "degraded");
  assert.equal(byKey.strategyLedger.metric, "— pass");
  assert.equal(byKey.dataIntegrity.status, "degraded");
  assert.equal(byKey.dataIntegrity.metric, "—");
});
