// Item 4: plan card state from config/tape-plan.json + the latest 1m series. Read-only.
//
// Truthfulness contract (PR1013 secondary surface): the extras plan card uses the SAME
// plan-availability gate (planAvailability), the SAME actual-tick/freshness gate
// (tapeEvaluationAllowed) and the SAME trigger evaluator (evaluateTrigger) as the main
// /tape screen. It never runs a second, looser trigger logic (no one-close TRIGGERED, no
// TARGET/STOPPED lifecycle inferred from bar touches, no calendar-date-only plan check),
// and it reports UNAVAILABLE (historical reference only) for a bad clock, a missing
// actual tick, a session mismatch, or a plan-source conflict.
import {
  normalizeSnapshot,
  type TapeLevel,
  type TapeSnapshot,
} from "@/lib/tapeDerive";
import {
  evaluateTrigger,
  normalizePlan,
  type PlanAvailability,
  type TapePlan,
  type TriggerCheck,
} from "@/lib/tapePlan";

export const VOID_AFTER_CT_MIN = 14 * 60; // 2:00 PM CT (display note only — never a trigger state)

export interface PlanCardGate {
  /** Result of tapeEvaluationAllowed on the serving snapshot (fresh + actual tick + no fetch failure). */
  evaluationAllowed: boolean;
  /** Result of planAvailability for the plan file, or null when it was not computed. */
  planAvail: PlanAvailability | null;
}

export interface PlanCardLeg {
  side: "long" | "short";
  trigger: number;
  stop: number | null;
  targets: number[];
  /** Evaluated gate checks from the MAIN trigger evaluator. Empty while not evaluated. */
  checks: TriggerCheck[];
  /** Main-evaluator status (ARMED/TRIGGERED/FAILED), or the historical placeholder. */
  state: string;
  reason: string | null;
  ifThen: string | null;
  distance: number | null;
  historical: boolean;
}

export interface PlanCardResult {
  ok: boolean;
  error?: string;
  date: string | null;
  note: string | null;
  /** Display note only: new legs are void after 2:00 PM CT. */
  pastVoid: boolean;
  /** True when the plan may not back actionable trigger state (bad clock/tick/session/plan). */
  unavailable: boolean;
  reason: string | null;
  legs: PlanCardLeg[];
}

const HISTORICAL_STATE = "HISTORICAL — NOT EVALUATED";

function ctMinutes(epochS: number): number {
  const s = new Date(epochS * 1000).toLocaleString("en-US", { timeZone: "America/Chicago", hour12: false, hour: "2-digit", minute: "2-digit" });
  const [h, m] = s.split(":").map(Number);
  return (h % 24) * 60 + m;
}

function distTo(last: number | null, trigger: number): number | null {
  return last !== null && Number.isFinite(last) ? +(last - trigger).toFixed(2) : null;
}

/**
 * Build the extras plan card. `planRaw` is the parsed plan file, `flow` the raw
 * flow-latest snapshot. `gate` carries the main-screen availability decisions; when the
 * gate is withheld (stale/conflicting plan, no actual tick, bad clock, unusable snapshot)
 * the card reports UNAVAILABLE and lists the plan levels as historical reference only.
 * Never throws; never infers fills or target/stop lifecycle.
 */
export function readPlanCard(planRaw: unknown, flow: unknown, nowS: number, gate: PlanCardGate | null): PlanCardResult {
  const pastVoid = ctMinutes(nowS) >= VOID_AFTER_CT_MIN;
  const plan: TapePlan | null = normalizePlan(planRaw);
  if (!plan) {
    return { ok: false, error: "plan missing or invalid", date: null, note: null, pastVoid, unavailable: true, reason: "plan missing or invalid", legs: [] };
  }
  const snap: TapeSnapshot | null = normalizeSnapshot(flow);
  const usable = !!gate?.planAvail?.usable;
  const allowed = !!gate?.evaluationAllowed;

  if (!usable || !allowed || !snap) {
    const reason = !usable
      ? gate?.planAvail?.reason ?? "plan availability unknown — not evaluated"
      : !allowed
        ? "no fresh snapshot with an actual tick — trigger state not evaluated"
        : "snapshot unusable — trigger state not evaluated";
    const legs: PlanCardLeg[] = (["long", "short"] as const).flatMap((side): PlanCardLeg[] => {
      const p = plan[side];
      if (!p) return [];
      return [{
        side,
        trigger: p.trigger,
        stop: p.stop,
        targets: p.targets,
        checks: [],
        state: HISTORICAL_STATE,
        reason: null,
        ifThen: null,
        distance: distTo(snap?.price.last ?? null, p.trigger),
        historical: true,
      }];
    });
    return { ok: true, date: plan.date, note: plan.note, pastVoid, unavailable: true, reason, legs };
  }

  const legs = (["long", "short"] as const).flatMap((side): PlanCardLeg[] => {
    const p = plan[side];
    if (!p) return [];
    const ev = evaluateTrigger(side, p, snap, plan.nqRef, plan.lookbackMin, plan.failedExpiryMin);
    return [{
      side,
      trigger: p.trigger,
      stop: p.stop,
      targets: p.targets,
      checks: ev.checks,
      state: ev.status,
      reason: ev.reason,
      ifThen: ev.ifThen,
      distance: distTo(snap.price.last, p.trigger),
      historical: false,
    }];
  });
  return { ok: true, date: plan.date, note: plan.note, pastVoid, unavailable: false, reason: null, legs };
}

/** TapeLevel rows for the plan's extra levels (historical overlays are labelled by the caller). */
export function planExtraLevels(plan: TapePlan): TapeLevel[] {
  return plan.extraLevels;
}
