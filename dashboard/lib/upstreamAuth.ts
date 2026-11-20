/** Backend credentials are server-managed, not the visitor's dashboard login. */
export function upstreamAuthFailure(status: number, service: string): Response | null {
  if (status !== 401 && status !== 403) return null;
  return Response.json({
    error: "upstream_auth_failed",
    service,
    message: "Dashboard login accepted, but the backend rejected its server credentials. Check the backend connection configuration.",
  }, { status: 502, headers: { "Cache-Control": "no-store" } });
}
