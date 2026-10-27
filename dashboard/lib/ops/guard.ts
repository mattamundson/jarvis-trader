/**
 * Access guard for the private /ops page (defense in depth on top of middleware.ts Basic Auth).
 *
 * middleware.ts already covers /ops and /api/ops: neither is in isPublicReadOnlyPath, so credentials are
 * enforced when DASHBOARD_AUTH_USER/PASS are set and a hosted deployment without them fails closed.
 * Two cases still need a page-level answer, because middleware lets them through:
 *   - plain localhost with no credentials: fine, but only if the request really is addressed to localhost
 *     (a tunnel or LAN host name with no credentials must not reach the Hermes record);
 *   - DASHBOARD_AUTH_DISABLED=1 (deliberate public demo): /ops is never part of a demo.
 * The Hermes files exist only on the local machine, so a hosted deployment is refused outright.
 */

export interface OpsAccessInput {
  host?: string | null;
  user?: string | null;
  pass?: string | null;
  vercel?: string | null;
  /** OPS_DISABLED=1 turns the page off entirely. */
  opsDisabled?: string | null;
}

export interface OpsAccessDecision {
  allowed: boolean;
  reason: "ops-disabled" | "hosted" | "basic-auth" | "localhost" | "remote-without-auth";
}

export function isLocalHost(hostHeader: string | null | undefined): boolean {
  if (!hostHeader) return false;
  let h = hostHeader.trim().toLowerCase();
  if (h.startsWith("[")) h = h.slice(0, h.indexOf("]") + 1); // [::1]:3010 -> [::1]
  else h = h.replace(/:\d+$/, "");
  return h === "localhost" || h === "127.0.0.1" || h === "[::1]";
}

export function decideOpsAccess(i: OpsAccessInput): OpsAccessDecision {
  if (i.opsDisabled === "1") return { allowed: false, reason: "ops-disabled" };
  if (i.vercel === "1") return { allowed: false, reason: "hosted" };
  if (i.user && i.pass) return { allowed: true, reason: "basic-auth" };
  if (isLocalHost(i.host)) return { allowed: true, reason: "localhost" };
  return { allowed: false, reason: "remote-without-auth" };
}

export function readOpsAccessEnv(host: string | null, env: NodeJS.ProcessEnv = process.env): OpsAccessInput {
  return {
    host,
    user: env.DASHBOARD_AUTH_USER,
    pass: env.DASHBOARD_AUTH_PASS,
    vercel: env.VERCEL,
    opsDisabled: env.OPS_DISABLED,
  };
}
