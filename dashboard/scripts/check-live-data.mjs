#!/usr/bin/env node
/**
 * check-live-data.mjs — is the dashboard actually getting LIVE data?
 *
 * Hits the engine endpoints the dashboard depends on and classifies each:
 *   LIVE        — 200 with real, non-empty data
 *   EMPTY       — 200 but empty / all-null / carries an `error` marker (feed degraded)
 *   AUTH/HTTP   — 4xx (bad/missing API key, wrong path)
 *   UNREACHABLE — connection refused / timeout / 5xx (the service is down)
 *
 * Run it ON THE MACHINE where the engine runs (or with the URLs pointed at it):
 *   cd dashboard && node scripts/check-live-data.mjs
 * Env (same names the dashboard proxy uses):
 *   ENGINE_URL           (default http://localhost:8010)   — or ENGINE_INTERNAL_URL / NEXT_PUBLIC_ENGINE_URL
 *   ENGINE_API_KEY       (or NEXT_PUBLIC_ENGINE_API_KEY)
 *   MASTER_API_URL       (default http://127.0.0.1:8030)   — the external honest-trade-record service
 *
 * Exit code: 0 if the engine is reachable, 1 if the engine itself is UNREACHABLE.
 * This does NOT judge whether the data is *correct* — only whether real data is flowing.
 */

const ENGINE =
  process.env.ENGINE_URL ||
  process.env.ENGINE_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_ENGINE_URL ||
  "http://localhost:8010";
const MASTER = process.env.MASTER_API_URL || process.env.NEXT_PUBLIC_MASTER_API_URL || "http://127.0.0.1:8030";
const API_KEY = process.env.ENGINE_API_KEY || process.env.NEXT_PUBLIC_ENGINE_API_KEY || "";
const TIMEOUT_MS = 8000;

// (label, base, path). Extend freely — these are the core overview data sources.
const CHECKS = [
  ["Engine health", ENGINE, "/health"],
  ["Prices (Signal Flow / Watchlist)", ENGINE, "/prices/snapshot"],
  ["Safety / kill-switch", ENGINE, "/safety/status"],
  ["P&L truth (honest realized)", ENGINE, "/pnl/truth"],
  ["Pipeline signal debug", ENGINE, "/pipeline/signal-debug"],
  ["Validation scorecard", ENGINE, "/validation"],
  ["Master-API (honest trade record)", MASTER, "/health"],
];

function classify(status, body) {
  if (status >= 500) return ["UNREACHABLE", `HTTP ${status}`];
  if (status === 401 || status === 403) return ["AUTH", `HTTP ${status} — check ENGINE_API_KEY`];
  if (status >= 400) return ["HTTP", `HTTP ${status}`];
  if (body == null) return ["EMPTY", "null body"];
  if (typeof body === "object") {
    if (body.error) return ["EMPTY", `error: ${String(body.error).slice(0, 60)}`];
    const vals = Array.isArray(body) ? body : Object.values(body);
    if (vals.length === 0) return ["EMPTY", "no rows/fields"];
    const nullish = (v) =>
      v == null ||
      (typeof v === "object" && v !== null && (v.error != null || Object.values(v).every((x) => x == null)));
    if (vals.every(nullish)) return ["EMPTY", "all fields null (feed degraded)"];
  }
  return ["LIVE", "real data present"];
}

async function hit(base, path) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(base + path, {
      headers: API_KEY ? { "X-API-Key": API_KEY } : {},
      signal: ctrl.signal,
    });
    let body = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    return classify(res.status, body);
  } catch (e) {
    return ["UNREACHABLE", e.name === "AbortError" ? "timeout" : (e.cause?.code || e.message)];
  } finally {
    clearTimeout(t);
  }
}

const ICON = { LIVE: "🟢", EMPTY: "🟡", AUTH: "🟠", HTTP: "🟠", UNREACHABLE: "🔴" };

const main = async () => {
  console.log(`\nLive-data check  engine=${ENGINE}  master-api=${MASTER}  key=${API_KEY ? "set" : "MISSING"}\n`);
  const rows = [];
  for (const [label, base, path] of CHECKS) {
    const [verdict, note] = await hit(base, path);
    rows.push({ label, path, verdict, note });
    console.log(`  ${ICON[verdict] || "⚪"} ${verdict.padEnd(11)} ${label.padEnd(38)} ${path.padEnd(24)} ${note}`);
  }
  const engineHealth = rows.find((r) => r.path === "/health" && r.label.startsWith("Engine"));
  const live = rows.filter((r) => r.verdict === "LIVE").length;
  console.log(`\n  ${live}/${rows.length} sources returning LIVE data.`);
  if (engineHealth?.verdict === "UNREACHABLE") {
    console.log("  🔴 Engine itself is UNREACHABLE — nothing on the dashboard can be live. Start the engine (PM2: jarvis-engine).\n");
    process.exit(1);
  }
  if (live < rows.length) {
    console.log("  🟡 Some sources are empty/degraded — expected off-hours or if IB Gateway / master-api are down.\n");
  } else {
    console.log("  🟢 All core sources live.\n");
  }
  process.exit(0);
};

main();
