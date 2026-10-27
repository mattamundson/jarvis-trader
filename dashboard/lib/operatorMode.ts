/**
 * Operator-dashboard mode.
 *
 * Scoreboard mode is on unless DASHBOARD_SCOREBOARD_MODE is explicitly
 * 0/false/no/off. In that mode the engine proxy rejects mutations, so a
 * hidden order button cannot reach the broker. The engine's own paper
 * path is unchanged.
 *
 * Vercel sets VERCEL=1. That audience renders gates and lockout only.
 */

const SCOREBOARD_OFF = new Set(["0", "false", "no", "off"]);

export function isScoreboardMode(env: NodeJS.ProcessEnv = process.env): boolean {
  const raw = (env.DASHBOARD_SCOREBOARD_MODE ?? "1").trim().toLowerCase();
  return !SCOREBOARD_OFF.has(raw);
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
