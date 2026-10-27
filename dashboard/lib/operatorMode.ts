/** Server-side deployment detection; no client-controlled override. */
export function isVercelDeployment(): boolean {
  return process.env.VERCEL === "1";
}

/** The operator dashboard is read-only on both local and hosted deployments. */
export function scoreboardRejectsMethod(method: string): boolean {
  return !["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase());
}
