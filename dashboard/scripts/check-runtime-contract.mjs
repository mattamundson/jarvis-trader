#!/usr/bin/env node
/**
 * Verifies the served dashboard/engine runtime contract.
 *
 * This catches the failure mode where /health is green but the dashboard proxy
 * or local runtime surfaces have drifted from the shapes the UI actually reads.
 */

const DASHBOARD =
  process.env.DASHBOARD_URL ||
  process.env.NEXT_PUBLIC_DASHBOARD_URL ||
  "http://127.0.0.1:3010";

const TIMEOUT_MS = Number(process.env.RUNTIME_CONTRACT_TIMEOUT_MS || 20_000);

export function dashboardHeaders() {
  const headers = {};
  const basicAuth = process.env.DASHBOARD_BASIC_AUTH;
  if (basicAuth) {
    headers.Authorization = `Basic ${Buffer.from(basicAuth).toString("base64")}`;
  }
  return headers;
}

function timeoutSignal() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  return { signal: controller.signal, clear: () => clearTimeout(timer) };
}

async function getJson(path) {
  const { signal, clear } = timeoutSignal();
  try {
    const response = await fetch(`${DASHBOARD}${path}`, {
      cache: "no-store",
      signal,
      headers: dashboardHeaders(),
    });
    let body = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    return { response, body };
  } finally {
    clear();
  }
}

function fail(message, detail = undefined) {
  console.error(`RUNTIME CONTRACT FAILED: ${message}`);
  if (detail !== undefined) {
    console.error(JSON.stringify(detail, null, 2));
  }
  process.exitCode = 1;
}

function isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function isNullableString(value) {
  return value == null || typeof value === "string";
}

export function validateHealthContract(body) {
  const errors = [];
  if (body?.status !== "ok") errors.push("status must equal 'ok'");
  if (typeof body?.live_trading !== "boolean") errors.push("live_trading must be boolean");
  if (typeof body?.kill_switch_active !== "boolean") errors.push("kill_switch_active must be boolean");
  if (typeof body?.ibkr_connected !== "boolean") errors.push("ibkr_connected must be boolean");
  return errors;
}

export function validateBrokerContract(body) {
  const errors = [];
  const schwabStatus = body?.schwab?.status;
  if (!schwabStatus) {
    errors.push("schwab.status is missing");
    return errors;
  }

  const discrepancies = Array.isArray(body?.reconciliation?.discrepancies)
    ? body.reconciliation.discrepancies
    : [];
  const discrepancyTypes = new Set(discrepancies.map((item) => item?.type).filter(Boolean));

  if (schwabStatus === "disabled_by_policy") {
    if (discrepancyTypes.has("paper_only")) {
      errors.push("Schwab disabled_by_policy cannot still report paper_only");
    }
    if (!discrepancyTypes.has("paper_unverified")) {
      errors.push("Schwab disabled_by_policy must include paper_unverified");
    }
    const missingDetail = discrepancies.find(
      (item) =>
        item?.broker_family === "schwab" &&
        item?.type === "paper_unverified" &&
        !String(item?.detail || "").includes("SCHWAB_READY=false"),
    );
    if (missingDetail) {
      errors.push("Schwab paper_unverified discrepancy is missing SCHWAB_READY=false detail");
    }
  }

  return errors;
}

export function validateSafetyStatusContract(body) {
  const errors = [];
  if (typeof body?.kill_switch_active !== "boolean") errors.push("kill_switch_active must be boolean");
  if (!isNullableString(body?.kill_switch_reason)) errors.push("kill_switch_reason must be string|null");
  if (!isFiniteNumber(body?.daily_pnl)) errors.push("daily_pnl must be finite number");
  if (!isFiniteNumber(body?.daily_pnl_pct)) errors.push("daily_pnl_pct must be finite number");
  if (!isFiniteNumber(body?.daily_limit_pct)) errors.push("daily_limit_pct must be finite number");
  if (typeof body?.daily_limit_breached !== "boolean") errors.push("daily_limit_breached must be boolean");
  if (!isFiniteNumber(body?.drawdown_pct)) errors.push("drawdown_pct must be finite number");
  if (!isFiniteNumber(body?.drawdown_limit_pct)) errors.push("drawdown_limit_pct must be finite number");
  if (typeof body?.drawdown_breached !== "boolean") errors.push("drawdown_breached must be boolean");
  if (!isFiniteNumber(body?.portfolio_equity)) errors.push("portfolio_equity must be finite number");
  if (!isFiniteNumber(body?.current_balance)) errors.push("current_balance must be finite number");
  return errors;
}

export function validateTradingStatusContract(body) {
  const errors = [];
  if (!isFiniteNumber(body?.summary?.total)) errors.push("summary.total must be finite number");
  if (!isFiniteNumber(body?.summary?.tradeable)) errors.push("summary.tradeable must be finite number");
  if (!isFiniteNumber(body?.summary?.enabled)) errors.push("summary.enabled must be finite number");
  if (!isFiniteNumber(body?.summary?.disagreements)) errors.push("summary.disagreements must be finite number");
  if (!Array.isArray(body?.symbols)) {
    errors.push("symbols must be an array");
    return errors;
  }

  for (const [index, row] of body.symbols.entries()) {
    if (typeof row?.symbol !== "string" || row.symbol.length === 0) errors.push(`symbols[${index}].symbol must be non-empty string`);
    if (typeof row?.enabled !== "boolean") errors.push(`symbols[${index}].enabled must be boolean`);
    if (typeof row?.authorized !== "boolean") errors.push(`symbols[${index}].authorized must be boolean`);
    if (typeof row?.tradeable !== "boolean") errors.push(`symbols[${index}].tradeable must be boolean`);
    if (typeof row?.config_agrees !== "boolean") errors.push(`symbols[${index}].config_agrees must be boolean`);
    if (!Array.isArray(row?.disagreements)) errors.push(`symbols[${index}].disagreements must be array`);
  }

  return errors;
}

export function validateRuntimeSnapshotContract(body) {
  const errors = [];
  if (!body || typeof body !== "object") return ["runtime snapshot body must be an object"];
  if (!isNullableString(body.captured_at_utc)) errors.push("captured_at_utc must be string|null");
  if (!body.contract || typeof body.contract !== "object") {
    errors.push("contract section is missing");
  } else {
    if (typeof body.contract.required_sections_present !== "boolean") {
      errors.push("contract.required_sections_present must be boolean");
    }
    if (!Array.isArray(body.contract.missing_sections)) {
      errors.push("contract.missing_sections must be array");
    }
    if (body.contract.required_sections_present === false) {
      errors.push(`runtime snapshot missing required sections: ${(body.contract.missing_sections || []).join(", ")}`);
    }
  }
  if (!body.source_integrity || typeof body.source_integrity !== "object") {
    errors.push("source_integrity section is missing");
  } else {
    if (!Array.isArray(body.source_integrity.checks)) {
      errors.push("source_integrity.checks must be array");
    }
    if (!["pass", "fail", "unknown"].includes(body.source_integrity.overall)) {
      errors.push("source_integrity.overall must be pass|fail|unknown");
    }
  }
  return errors;
}

function assertResponseOk(label, result) {
  if (!result.response.ok) {
    throw new Error(`${label} did not return 2xx (status ${result.response.status})`);
  }
}

function assertContract(label, errors, body) {
  if (errors.length > 0) {
    const error = new Error(`${label} contract invalid`);
    error.detail = { errors, body };
    throw error;
  }
}

function shouldRun(name) {
  const raw = process.env.RUNTIME_CONTRACT_CHECKS;
  if (!raw) return true;
  return raw
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .includes(name);
}

export async function main() {
  const summary = { dashboard: DASHBOARD };

  if (shouldRun("health")) {
    const health = await getJson("/api/engine/health");
    assertResponseOk("/api/engine/health", health);
    assertContract("/api/engine/health", validateHealthContract(health.body), health.body);
    summary.health_status = health.body.status;
    summary.ibkr_connected = health.body.ibkr_connected;
  }

  if (shouldRun("broker")) {
    const broker = await getJson("/api/engine/brokers/positions");
    assertResponseOk("/api/engine/brokers/positions", broker);
    assertContract("/api/engine/brokers/positions", validateBrokerContract(broker.body), broker.body);
    summary.schwab_status = broker.body?.schwab?.status ?? null;
  }

  if (shouldRun("safety")) {
    const safety = await getJson("/api/engine/safety/status");
    assertResponseOk("/api/engine/safety/status", safety);
    assertContract("/api/engine/safety/status", validateSafetyStatusContract(safety.body), safety.body);
    summary.portfolio_equity = safety.body?.portfolio_equity ?? null;
  }

  if (shouldRun("trading-status")) {
    const tradingStatus = await getJson("/api/engine/trading-status");
    assertResponseOk("/api/engine/trading-status", tradingStatus);
    assertContract("/api/engine/trading-status", validateTradingStatusContract(tradingStatus.body), tradingStatus.body);
    summary.trading_symbols = Array.isArray(tradingStatus.body?.symbols) ? tradingStatus.body.symbols.length : null;
    summary.trading_disagreements = tradingStatus.body?.summary?.disagreements ?? null;
  }

  if (shouldRun("runtime-snapshot")) {
    const runtimeSnapshot = await getJson("/api/runtime-snapshot");
    assertResponseOk("/api/runtime-snapshot", runtimeSnapshot);
    assertContract("/api/runtime-snapshot", validateRuntimeSnapshotContract(runtimeSnapshot.body), runtimeSnapshot.body);
    summary.snapshot_contract_complete = runtimeSnapshot.body?.contract?.required_sections_present ?? null;
    summary.source_integrity_overall = runtimeSnapshot.body?.source_integrity?.overall ?? null;
  }

  console.log("Runtime contract OK");
  console.log(JSON.stringify(summary, null, 2));
}

const isDirectRun = process.argv[1] && new URL(`file://${process.argv[1]}`).href === import.meta.url;

if (isDirectRun) {
  main().catch((error) => {
    fail(error instanceof Error ? error.message : String(error), error?.detail);
  });
}
