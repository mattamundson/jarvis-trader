import { test } from "node:test";
import assert from "node:assert/strict";
import {
  compactCount,
  deriveCommandCenterDailyBriefSummaryRows,
  deriveCommandCenterOperationsSummaryRows,
  deriveCommandCenterShellRegions,
  deriveCommandCenterStatusStripState,
  deriveCommandCenterTrustAuditSummaryRows,
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

test("operations summary rows preserve risk and execution states", () => {
  const rows = deriveCommandCenterOperationsSummaryRows({
    health: {
      status: "ok",
      kill_switch_active: false,
      uptime_seconds: 60,
      ibkr_connected: true,
      ibkr_data_connected: true,
      paper_trading: true,
      version: "fixture",
    },
    healthErr: false,
    safety: {
      daily_pnl: 0,
      equity_peak: 10000,
      drawdown_pct: -0.0125,
      orders_last_minute: 2,
      orders_per_minute_limit: 10,
      kill_switch_active: false,
    },
    safetyErr: false,
    execution: { label: "CONNECTED", detail: "broker ack" },
  });

  assert.deepEqual(rows.map((row) => [row.label, row.state, row.detail, row.tone]), [
    ["Kill Switch", "clear", "operations risk surface", "ok"],
    ["Order Rate", "2/10", "orders per minute limit", "unknown"],
    ["Drawdown", "1.25%", "live safety drawdown", "unknown"],
    ["Broker Execution", "connected", "broker ack", "ok"],
    ["Data Leg", "online", "IBKR data connection flag", "ok"],
  ]);
});

test("operations summary rows degrade independently when sources fail", () => {
  const rows = deriveCommandCenterOperationsSummaryRows({
    health: undefined,
    healthErr: true,
    safety: undefined,
    safetyErr: true,
    execution: { label: "NO BROKER ACK", detail: "unverified path" },
  });

  assert.deepEqual(rows.map((row) => [row.label, row.state, row.detail]), [
    ["Kill Switch", "unknown", "safety endpoint unavailable"],
    ["Order Rate", "unknown", "order limiter unavailable"],
    ["Drawdown", "unknown", "drawdown unavailable"],
    ["Broker Execution", "no broker ack", "unverified path"],
    ["Data Leg", "unknown", "health endpoint unavailable"],
  ]);
});

test("daily brief summary rows derive session and market facts", () => {
  const rows = deriveCommandCenterDailyBriefSummaryRows({
    health: {
      status: "ok",
      kill_switch_active: false,
      uptime_seconds: 60,
      ibkr_connected: true,
      paper_trading: true,
    },
    sessionToday: {
      date: "2026-09-01",
      session: "RTH",
      closed_trades: 2,
      open_trades: 1,
      gross_pnl: -42.5,
      wins: 1,
      losses: 1,
      win_rate: 0.5,
      best_trade: 25,
      worst_trade: -67.5,
      avg_pnl: -21.25,
      symbols_traded: ["MES"],
      last_updated: "2026-09-01T15:00:00.000Z",
    },
    sessionTodayErr: false,
    macro: { regime: "TREND", vix_regime: "LOW", timestamp: "2026-09-01T15:00:00.000Z" },
    execution: {
      label: "CONNECTED",
      tone: "bull",
      detail: "Broker acknowledged the execution path.",
    },
  });

  assert.deepEqual(rows.map((row) => [row.label, row.state, row.detail, row.tone]), [
    ["Mode", "paper", "from /health paper_trading", "ok"],
    ["Execution", "connected", "Broker acknowledged the execution path.", "ok"],
    ["Trades", "3", "closed plus open", "ok"],
    ["Session P&L", "-$42.50", "gross session P&L", "ok"],
    ["Open", "1", "open session trades", "ok"],
    ["Market", "trend", "macro/regime context", "ok"],
  ]);
});

test("daily brief summary rows keep unknowns explicit", () => {
  const rows = deriveCommandCenterDailyBriefSummaryRows({
    health: undefined,
    sessionToday: undefined,
    sessionTodayErr: true,
    macro: undefined,
    execution: {
      label: "EXEC ?",
      tone: "neutral",
      detail: "No health data available.",
    },
  });

  assert.deepEqual(rows.map((row) => [row.label, row.state, row.detail, row.tone]), [
    ["Mode", "unknown", "from /health paper_trading", "unknown"],
    ["Execution", "exec ?", "No health data available.", "unknown"],
    ["Trades", "unknown", "session endpoint unavailable", "unknown"],
    ["Session P&L", "unknown", "gross session P&L", "unknown"],
    ["Open", "unknown", "open session trades", "unknown"],
    ["Market", "unknown", "macro/regime context", "unknown"],
  ]);
});

test("trust audit summary rows derive liveness and evidence counts", () => {
  const rows = deriveCommandCenterTrustAuditSummaryRows({
    health: {
      status: "ok",
      kill_switch_active: false,
      uptime_seconds: 60,
      ibkr_connected: true,
      ibkr_data_connected: true,
    },
    healthErr: false,
    barQuality: { window_hours: 168, total_rejections: 4, gate_active: true },
    barQualityErr: false,
    edgeLedger: { total: 9, n_pass: 2, n_fail: 7, n_other: 0 },
    edgeLedgerErr: false,
  });

  assert.deepEqual(rows.map((row) => [row.label, row.state, row.detail]), [
    ["Liveness", "ok", "engine status"],
    ["Provenance", "live", "3/3 live sources"],
    ["Bar Rejects", "4", "gate active · 168h"],
    ["Edge Ledger", "2/9", "PASS 2 · FAIL 7"],
    ["Data Leg", "live", "IBKR market-data provenance"],
    ["Post-Trade", "linked", "/trust-pane execution + quality"],
  ]);
});

test("trust audit summary rows keep unavailable evidence unknown", () => {
  const rows = deriveCommandCenterTrustAuditSummaryRows({
    health: undefined,
    healthErr: true,
    barQuality: undefined,
    barQualityErr: true,
    edgeLedger: undefined,
    edgeLedgerErr: true,
  });

  assert.deepEqual(rows.map((row) => [row.label, row.state, row.detail, row.tone]), [
    ["Liveness", "unknown", "engine status", "unknown"],
    ["Provenance", "unknown", "0/3 live sources", "unknown"],
    ["Bar Rejects", "unknown", "bar-quality unavailable", "unknown"],
    ["Edge Ledger", "unknown", "edge ledger unavailable", "unknown"],
    ["Data Leg", "unknown", "IBKR market-data provenance", "unknown"],
    ["Post-Trade", "linked", "/trust-pane execution + quality", "ok"],
  ]);
});
