/**
 * Dashboard private-route access decision.
 *
 * Extracted from `middleware.ts` so the policy is unit-testable without importing
 * Next's ESM middleware surface.
 *
 * The dashboard is a trading control surface (positions, kill-switch state, order
 * approval) and its `/api/engine/*` proxy injects the engine API key server-side,
 * so an unauthenticated deployment does not merely leak a UI — it exposes the live
 * engine API to anyone with the URL.
 *
 * Policy:
 *   credentials present                -> "enforce" (Basic Auth)
 *   DASHBOARD_AUTH_DISABLED=1          -> "allow"   (deliberate local/CI opt-out)
 *   running on a hosted deployment     -> "deny"    (fail CLOSED)
 *   plain localhost / self-hosted      -> "allow"   (dev convenience)
 *
 * Fail-open was the previous behavior and produced exactly this incident: a Vercel
 * production deploy with no DASHBOARD_AUTH_* env vars served the entire dashboard
 * and engine proxy to the public internet. Hosted deployments must never serve
 * private routes unauthenticated — refusing traffic is the safe failure mode.
 */

export type DashboardAuthDecision = "enforce" | "allow" | "deny";

export interface DashboardAuthEnv {
  user?: string | null;
  pass?: string | null;
  /** DASHBOARD_AUTH_DISABLED — explicit opt-out, intended for local dev / CI. */
  disabled?: string | null;
  /** VERCEL — set to "1" by Vercel on every deployment (production and preview). */
  vercel?: string | null;
}

export interface DashboardAuthRequest {
  method?: string | null;
  host?: string | null;
  forwarded?: string | null;
  xForwardedFor?: string | null;
  xRealIp?: string | null;
}

const WRITE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function stripPort(host: string): string {
  const value = host.trim().toLowerCase();
  if (value.startsWith("[")) return value.slice(1, value.indexOf("]"));
  const colon = value.indexOf(":");
  return colon === -1 ? value : value.slice(0, colon);
}

function isLoopbackHost(host: string | null | undefined): boolean {
  if (!host) return false;
  const normalized = stripPort(host);
  return normalized === "localhost" || normalized === "127.0.0.1" || normalized === "::1";
}

function isLoopbackAddress(address: string | null | undefined): boolean {
  if (!address) return false;
  const first = address.split(",")[0]?.trim().toLowerCase();
  return first === "127.0.0.1" || first === "::1" || first === "[::1]" || first === "localhost";
}

function hasPublicForwardingEvidence(req: DashboardAuthRequest): boolean {
  return Boolean(
    req.forwarded ||
      (req.xForwardedFor && !isLoopbackAddress(req.xForwardedFor)) ||
      (req.xRealIp && !isLoopbackAddress(req.xRealIp)),
  );
}

function isLoopbackWrite(req?: DashboardAuthRequest): boolean {
  if (!req) return false;
  const method = (req.method ?? "").toUpperCase();
  if (!WRITE_METHODS.has(method)) return false;
  if (hasPublicForwardingEvidence(req)) return false;
  return isLoopbackHost(req.host) || isLoopbackAddress(req.xForwardedFor) || isLoopbackAddress(req.xRealIp);
}

export function decideDashboardAuth(env: DashboardAuthEnv, req?: DashboardAuthRequest): DashboardAuthDecision {
  // Configured credentials always win, even if the disable flag is also set.
  if (env.user && env.pass) return "enforce";

  // Explicit, deliberate opt-out.
  if (env.disabled === "1") return "allow";

  // Local automation may POST to the PM2/Next dashboard loopback endpoint even
  // when hosted-env sentinels are present in the process. Keep that allowance
  // narrow: mutating method + loopback evidence + no public forwarding headers.
  if (isLoopbackWrite(req)) return "allow";

  // Hosted deployment without credentials: refuse rather than expose.
  if (env.vercel === "1") return "deny";

  // Plain localhost / self-hosted dev without credentials.
  return "allow";
}

export function readDashboardAuthEnv(env: NodeJS.ProcessEnv = process.env): DashboardAuthEnv {
  return {
    user: env.DASHBOARD_AUTH_USER,
    pass: env.DASHBOARD_AUTH_PASS,
    disabled: env.DASHBOARD_AUTH_DISABLED,
    vercel: env.VERCEL,
  };
}
