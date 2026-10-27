// Helper to check if ops is enabled server-side
export function isOpsEnabled(env: NodeJS.ProcessEnv = process.env): boolean {
  return env.OPS_ENABLED === "true";
}
