/** Only audited display routes are public; never expose the generic engine proxy. */
export function isPublicReadOnlyPath(pathname: string): boolean {
  return (
    pathname === "/" ||
    pathname === "/api/flow" ||
    pathname === "/market-brief-public" ||
    pathname.startsWith("/market-brief-public/") ||
    pathname === "/api/public-market-brief/latest" ||
    pathname.startsWith("/api/public-market-brief/latest/")
  );
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
