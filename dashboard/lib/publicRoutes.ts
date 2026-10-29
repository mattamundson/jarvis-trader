import { isPublicEngineRead } from "@/lib/publicEngineReads";

/** All pages are public; proxy reads require an explicit allowlist. */
export function isPublicReadOnlyPath(pathname: string): boolean {
  if (/%|\\|\/\//.test(pathname) || pathname.split("/").some((part) => part === "." || part === "..")) return false;
  if (isWebSocketPath(pathname)) return false;
  if (!pathname.startsWith("/api/") && pathname !== "/api") return true;
  if (pathname.startsWith("/api/engine/")) {
    return isPublicEngineRead(pathname.slice("/api/engine".length));
  }
  return [
    "/api/domflow/domflow/mes/latest", "/api/domflow/domflow/mes/history",
    "/api/flow", "/api/flow/health", "/api/flow/metrics", "/api/fleet",
    "/api/runtime-snapshot", "/api/market-brief", "/api/public-market-brief/latest",
    "/api/jarvis/readiness-scorecard", "/api/spx-intraday",
    "/api/master/master/status", "/api/master/master/finances/detail",
    "/api/master/master/trading/realized", "/api/master/master/scheduler/status",
    "/api/master/master/scheduler/runs",
    "/api/amo/api/health", "/api/amo/api/edge-verdict", "/api/amo/api/commodities",
    "/api/amo/api/signal-outcomes/aggregate", "/api/amo/api/scoreboard", "/api/amo/api/actionable",
  ].includes(pathname.replace(/\/$/, ""));
}

/**
 * Flow ingest endpoint has its own Bearer token auth (FLOW_INGEST_TOKEN).
 * Exempt POST /api/flow/ingest from Basic auth so pushers can authenticate
 * with their Bearer token directly. GET is not exempt.
 */
export function isFlowIngestPath(pathname: string, method: string): boolean {
  return pathname === "/api/flow/ingest" && method === "POST";
}

/**
 * Paths under `/ws/` carry WebSocket traffic.
 *
 * They are NOT public. The middleware matcher used to exclude the whole `ws/` prefix, which
 * meant any *ordinary* GET under `/ws/` skipped Basic Auth and was proxied straight to the
 * engine tunnel — disclosing the tunnel hostname to anonymous callers and exposing the
 * tunnel's unauthenticated surface. The prefix exclusion is gone; only a genuine WebSocket
 * handshake may bypass auth, because browsers cannot attach an Authorization header to one.
 */
export function isWebSocketPath(pathname: string): boolean {
  return pathname === "/ws" || pathname.startsWith("/ws/");
}

/** A real WebSocket handshake sends `Upgrade: websocket`. An ordinary GET does not. */
export function isWebSocketUpgrade(upgradeHeader: string | null): boolean {
  return (upgradeHeader ?? "").trim().toLowerCase() === "websocket";
}

/** Public display routes cannot be used for server actions or other writes. */
export function isPublicReadOnlyRequest(pathname: string, method: string): boolean {
  return (method === "GET" || method === "HEAD") && isPublicReadOnlyPath(pathname);
}
