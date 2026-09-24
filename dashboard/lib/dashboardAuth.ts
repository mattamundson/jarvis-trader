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

export function decideDashboardAuth(env: DashboardAuthEnv): DashboardAuthDecision {
  // Configured credentials always win, even if the disable flag is also set.
  if (env.user && env.pass) return "enforce";

  // Explicit, deliberate opt-out.
  if (env.disabled === "1") return "allow";

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