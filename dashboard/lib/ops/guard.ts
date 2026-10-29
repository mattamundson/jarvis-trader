/** Public read-only operations record. OPS_DISABLED still supports explicit opt-out. */
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
  reason: "ops-disabled" | "public-read-only";
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
  return { allowed: true, reason: "public-read-only" };
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
