/**
 * Operator-dashboard mode.
 *
 * Scoreboard mode is off by default (engine writes pass through). Set
 * DASHBOARD_SCOREBOARD_MODE=1 to enable read-only mode, which rejects
 * POST/PUT/PATCH/DELETE so order buttons cannot reach the broker.
 * The engine's own paper path is unchanged.
 *
 * Vercel sets VERCEL=1. That audience renders gates and lockout only.
 */

const SCOREBOARD_ON = new Set(["1", "true", "yes", "on"]);

export function isScoreboardMode(env: NodeJS.ProcessEnv = process.env): boolean {
  const raw = (env.DASHBOARD_SCOREBOARD_MODE ?? "0").trim().toLowerCase();
  return SCOREBOARD_ON.has(raw);
}

export function scoreboardRejectsMethod(
  method: string,
  env: NodeJS.ProcessEnv = process.env,
): boolean {
  if (!isScoreboardMode(env)) return false;
  const verb = method.toUpperCase();
  return verb === "POST" || verb === "PUT" || verb === "PATCH" || verb === "DELETE";
}

export function isVercelDeployment(env: NodeJS.ProcessEnv = process.env): boolean {
  return env.VERCEL === "1";
}
