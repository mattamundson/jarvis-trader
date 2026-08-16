/**
 * Process-supervision chip derivation (PRB-24) — pure, testable mirror of the
 * logic SystemLivenessCard renders for the "Supervision" chip on /health.
 *
 * WHY THIS EXISTS AS A STANDALONE FUNCTION
 * -----------------------------------------
 * Nothing structurally cross-checked pm2's belief about process state against
 * actual reality: pm2 jlist (what pm2 THINKS it supervises) and a live TCP
 * port + PID probe (what is ACTUALLY listening) could independently disagree
 * with nobody noticing — a WinError 10048 port-bind race left a healthy-but-
 * pm2-unsupervised orphan process serving :8010 for a stretch (2026-07-28/29),
 * and a separate audit found pm2 believed jarvis-dashboard/jarvis-engine were
 * errored/stopped while orphan processes actually served both ports. The
 * engine's `/health/supervision` (and `/health/full`'s `process_supervision`
 * subsystem) now cross-checks this; this module is the dashboard-side
 * contract for turning that response into a chip tone/value/sub without a
 * DOM, so the derivation can be locked with `node --test` the same way
 * `lib/executionPath.ts` locks execution-status honesty (D3-01).
 *
 * CONTRACT
 * --------
 * - `status === "mismatch"` is the ONLY tone that ever goes "bad" (red) — a
 *   confirmed disagreement between pm2 and the OS.
 * - `status === "unavailable"` (pm2 not on PATH, or the shell-out failed) is
 *   an environment fact, not a live incident — it renders "unknown" (gray),
 *   never red, matching the engine's own choice not to escalate `overall`
 *   for this case (see health_router.py's PRB-24 `/health/full` comment).
 * - Any consumer render "Engine unreachable" / SWR error must resolve to
 *   "unknown" regardless of payload content — a stale supervision reading
 *   from before the engine dropped must never be shown as current.
 */

import type { ProcessSupervisionHealth } from "./api";

export type SupervisionTone = "ok" | "warn" | "bad" | "unknown";

export interface SupervisionChipState {
  tone: SupervisionTone;
  value: string;
  /** Name of the first mismatched app, or a short reason — undefined when nothing to show. */
  sub?: string;
}

export function supervisionChipState(
  supervision: ProcessSupervisionHealth | undefined,
  offline: boolean
): SupervisionChipState {
  if (offline || !supervision) {
    return { tone: "unknown", value: "—" };
  }

  const status = supervision.status;

  if (status === "mismatch") {
    const mismatchedApp = Object.entries(supervision.details?.apps ?? {}).find(
      ([, app]) => app.mismatch_reason
    );
    return { tone: "bad", value: "MISMATCH", sub: mismatchedApp?.[0] };
  }

  if (status === "ok") {
    return { tone: "ok", value: "IN SYNC" };
  }

  if (status === "unavailable") {
    return { tone: "unknown", value: "N/A", sub: "pm2 unreachable" };
  }

  // status === "error" or any unexpected/future value — surface as unknown,
  // never silently green.
  return { tone: "unknown", value: "UNKNOWN" };
}
