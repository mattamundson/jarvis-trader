#!/usr/bin/env node
/**
 * Verifies the served dashboard/engine runtime contract.
 *
 * This catches the failure mode where /health is green but the dashboard proxy
 * is missing runtime env or the broker endpoint is still serving stale code.
 */

const DASHBOARD =
  process.env.DASHBOARD_URL ||
  process.env.NEXT_PUBLIC_DASHBOARD_URL ||
  "http://127.0.0.1:3010";

const TIMEOUT_MS = Number(process.env.RUNTIME_CONTRACT_TIMEOUT_MS || 20_000);

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

async function main() {
  const health = await getJson("/api/engine/health");
  if (!health.response.ok) {
    return fail("dashboard proxy /api/engine/health did not return 2xx", {
      status: health.response.status,
      body: health.body,
    });
  }
  if (health.body?.status !== "ok") {
    return fail("engine health through dashboard proxy is not ok", health.body);
  }

  const broker = await getJson("/api/engine/brokers/positions");
  if (!broker.response.ok) {
    return fail("dashboard proxy /api/engine/brokers/positions did not return 2xx", {
      status: broker.response.status,
      body: broker.body,
    });
  }

  const schwabStatus = broker.body?.schwab?.status;
  if (!schwabStatus) {
    return fail("broker response is missing schwab.status; served contract is stale or proxy auth is wrong", broker.body);
  }

  const discrepancies = Array.isArray(broker.body?.reconciliation?.discrepancies)
    ? broker.body.reconciliation.discrepancies
    : [];
  const discrepancyTypes = new Set(discrepancies.map((item) => item?.type).filter(Boolean));

  if (schwabStatus === "disabled_by_policy") {
    if (discrepancyTypes.has("paper_only")) {
      return fail("Schwab is disabled_by_policy but equities are still classified paper_only", {
        discrepancyTypes: [...discrepancyTypes],
      });
    }
    if (!discrepancyTypes.has("paper_unverified")) {
      return fail("Schwab is disabled_by_policy but paper_unverified discrepancies are absent", {
        discrepancyTypes: [...discrepancyTypes],
      });
    }
    const missingDetail = discrepancies.find(
      (item) =>
        item?.broker_family === "schwab" &&
        item?.type === "paper_unverified" &&
        !String(item?.detail || "").includes("SCHWAB_READY=false"),
    );
    if (missingDetail) {
      return fail("Schwab paper_unverified discrepancy is missing policy detail", missingDetail);
    }
  }

  console.log("Runtime contract OK");
  console.log(
    JSON.stringify(
      {
        dashboard: DASHBOARD,
        health_status: health.body.status,
        ibkr_connected: health.body.ibkr_connected,
        schwab_status: schwabStatus,
        discrepancy_types: [...discrepancyTypes].sort(),
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  fail(error instanceof Error ? error.message : String(error));
});
