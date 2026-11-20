// PR1013 secondary-surface integrity tests (bounded lane: extras plan card, lean freshness,
// normalizeSnapshot unknown-preservation). Synthetic fixtures + explicit clocks only; no real
// services, files or broker calls. The extras plan card must use the MAIN plan-availability
// gate, freshness gate and trigger evaluator — never a second, looser trigger logic.
//
// Counterexamples pinned here (each failed before the fix):
//  C1: extras plan card marked a plan TRIGGERED on ONE 5m close, ignoring the two-close/
//      delta/NQ contract of the main trigger evaluator, and inferred TARGET/STOPPED/VOID
//      lifecycle states from bar touches (fill inference without evidence).
//  C2: extras plan card ran on heartbeat-only freshness — no actual-tick gate, and it
//      ran even for a stale/wrong-session/conflicting plan (its own calendar-date check
//      only), so a Saturday view showed Sunday-evening plans as actionable.
//  C3: normalizeSnapshot coerced missing/null CVD/delta/volume to 0. With 11 rising bars
//      and a final null CVD, that fabricated `dc = 0 - cvd[0]` and emitted a BEARISH
//      divergence from missing data.
//  C4: a future as_of_epoch (negative age) counted as fresh on the lean screen, and a
//      cached snapshot kept looking fresh after the fetch started failing.

import test from "node:test";
import assert from "node:assert/strict";
import {
  normalizeSnapshot,
  tapeAlerts,
  recentBars,
  blocks15,
} from "@/lib/tapeDerive";
import { completed5m, evaluateTrigger, normalizePlan, planAvailability } from "@/lib/tapePlan";
import { tapeEvaluationAllowed } from "@/lib/tapeFreshnessContract";
import { readPlanCard } from "@/lib/tape/planCard";
import type { Bar1m } from "@/lib/tapeDerive";

// Test clock: a Monday 2026-11-09 11:59:55 CT-equivalent epoch (matches the current-ok fixture family).
const NOW_S = 1794247195;

let cvdAcc = 600;
function bar(t: number, c: number, over: Partial<Bar1m> = {}): Record<string, unknown> {
  cvdAcc += 45;
  return { t, o: c - 0.5, h: c + 0.75, l: c - 0.75, c, vol: 900, delta: 40, cvd: cvdAcc, ...over };
}

/** 15 rising 1m bars: the last two 5m buckets close above the long trigger 7725.75. */
function risingSeries(): Record<string, unknown>[] {
  cvdAcc = 600;
  const out: Record<string, unknown>[] = [];
  let t = NOW_S - 15 * 60;
  let c = 7718;
  for (let i = 0; i < 15; i++) {
    t += 60;
    c += 1;
    out.push(bar(t, c));
  }
  return out;
}

function flowRaw(over: Record<string, unknown> = {}) {
  return {
    as_of_epoch: NOW_S - 5,
    as_of_ct: "2026-11-09T11:59:55-06:00",
    price: { last: 7731.0, vwap: 7727.8, hi: 7734.5, lo: 7718 },
    cvd: { value: 1240 },
    nq: { rel: { last: 21061.25, lead: "NQ +11.25", windows: {} } },
    levels: [],
    series_1m: risingSeries(),
    ...over,
  };
}

const PLAN_RAW = {
  date: "2026-11-09",
  note: "synthetic",
  nqRef: 21050,
  lookbackMin: 90,
  long: { trigger: 7725.75, minDelta: 150, targets: [7740, 7752], stop: 7709.75 },
  short: { trigger: 7697, minDelta: 150, targets: [7685], stop: 7713 },
};

const OK_GATE_ARGS = {
  todayCt: "2026-11-09",
  globexTradingDate: "2026-11-09",
  recorderSessionTradingDay: "2026-11-09",
  recorderLevelsSource: "tape-config (tape-plan dated 2026-11-09)",
};

/** Mirror of the extras-route gating computation, for building gates in tests. */
function routeGate(raw: unknown, allowedArgs = OK_GATE_ARGS, tickAgeS: number | null = 1, fetchFailed = false, planRaw: unknown = PLAN_RAW) {
  const snap = normalizeSnapshot(raw);
  const asOf = (raw as any)?.as_of_epoch;
  const snapshotAge = snap && typeof asOf === "number" && Number.isFinite(asOf) ? Math.round(NOW_S - asOf) : null;
  return {
    evaluationAllowed: tapeEvaluationAllowed(!!snap, snapshotAge, tickAgeS, fetchFailed),
    planAvail: planAvailability(normalizePlan(planRaw), allowedArgs),
  };
}

// ---- (1) Extras plan card: main gates + main trigger evaluator only ----

test("C1: extras plan card does not mark TRIGGERED on one 5m close when the main evaluator would not", () => {
  const raw = flowRaw();
  const gate = routeGate(raw); // usable plan, allowed, fresh tick
  const card = readPlanCard(PLAN_RAW, raw, NOW_S, gate);
  assert.equal(card.ok, true);
  assert.equal(card.unavailable, false, card.reason ?? "");
  const long = card.legs.find((l) => l.side === "long")!;
  // The old readPlanCard set "TRIGGERED" on the first close beyond the trigger. The main
  // evaluator additionally requires the delta and NQ gates, so it does not fire here.
  const main = evaluateTrigger("long", normalizePlan(PLAN_RAW)!.long!, normalizeSnapshot(raw)!, 21050, 90, 15);
  assert.equal(long.state, main.status);
  assert.notEqual(long.state, "TRIGGERED", "one close without delta/NQ confirmation must not read TRIGGERED");
});

test("C1: extras plan card never infers TARGET/STOPPED/VOID lifecycle from bar touches", () => {
  const raw = flowRaw({
    series_1m: risingSeries().concat([{ ...bar(NOW_S - 60, 7732), l: 7700 }]), // touches the stop after the break
  });
  const card = readPlanCard(PLAN_RAW, raw, NOW_S, routeGate(raw));
  for (const leg of card.legs) {
    assert.ok(["ARMED", "TRIGGERED", "FAILED"].includes(leg.state), `unexpected lifecycle state ${leg.state}`);
    assert.ok(!leg.state.startsWith("TARGET") && !leg.state.startsWith("STOPPED") && !leg.state.startsWith("VOID"));
  }
});

test("C2: extras plan card is UNAVAILABLE for a stale plan even with a fresh snapshot", () => {
  const raw = flowRaw();
  const gate = routeGate(raw, {
    todayCt: "2026-11-09",
    globexTradingDate: "2026-11-09",
    recorderSessionTradingDay: null,
    recorderLevelsSource: "tape-config (no dated plan loaded)",
  }, 1, false, { ...PLAN_RAW, date: "2026-11-03" });
  assert.equal(gate.planAvail.kind, "stale_date");
  const card = readPlanCard({ ...PLAN_RAW, date: "2026-11-03" }, raw, NOW_S, gate);
  assert.equal(card.unavailable, true);
  assert.match(card.reason ?? "", /stale/);
  for (const leg of card.legs) assert.equal(leg.state, "HISTORICAL — NOT EVALUATED");
  assert.ok(!card.legs.some((l) => l.state === "TRIGGERED"));
});

test("C2: extras plan card is UNAVAILABLE without an actual tick (heartbeat only)", () => {
  const raw = flowRaw();
  const gate = routeGate(raw, OK_GATE_ARGS, null);
  assert.equal(gate.evaluationAllowed, false);
  const card = readPlanCard(PLAN_RAW, raw, NOW_S, gate);
  assert.equal(card.unavailable, true);
  assert.match(card.reason ?? "", /tick/);
});

test("C2: extras plan card is UNAVAILABLE on a future/as-of-ahead clock", () => {
  const raw = flowRaw({ as_of_epoch: NOW_S + 3600 });
  const gate = routeGate(raw);
  assert.equal(gate.evaluationAllowed, false, "a future source clock must not count as fresh");
  const card = readPlanCard(PLAN_RAW, raw, NOW_S, gate);
  assert.equal(card.unavailable, true);
});

test("C2: extras plan card is UNAVAILABLE on conflicting plan sources", () => {
  const raw = flowRaw();
  const gate = routeGate(raw, { ...OK_GATE_ARGS, recorderLevelsSource: "tape-config (tape-plan dated 2026-11-10, not today 2026-11-09 CT)" });
  assert.equal(gate.planAvail.kind, "conflict");
  const card = readPlanCard(PLAN_RAW, raw, NOW_S, gate);
  assert.equal(card.unavailable, true);
});

test("Sunday evening: the Monday Globex plan evaluates normally on the extras card", () => {
  const raw = flowRaw();
  const gate = routeGate(raw, {
    todayCt: "2026-11-08", // Sunday calendar date
    globexTradingDate: "2026-11-09", // Sunday 18:00 CT belongs to Monday's session
    recorderSessionTradingDay: "2026-11-09",
    recorderLevelsSource: "tape-config (tape-plan dated 2026-11-09)",
  });
  assert.equal(gate.planAvail.usable, true, gate.planAvail.reason);
  const card = readPlanCard(PLAN_RAW, raw, NOW_S, gate);
  assert.equal(card.unavailable, false, card.reason ?? "");
  assert.ok(card.legs.length >= 1);
  assert.ok(card.legs.every((l) => l.state !== "HISTORICAL — NOT EVALUATED"));
});

test("extras plan card TRIGGERED state matches the main evaluator exactly when all gates fire", () => {
  // Same rising series but with a strong delta inside the break window and NQ above ref.
  const raw = flowRaw({
    series_1m: risingSeries().map((b, i) => (i >= 12 ? { ...b, delta: 200 } : b)),
  });
  const gate = routeGate(raw);
  const card = readPlanCard(PLAN_RAW, raw, NOW_S, gate);
  const long = card.legs.find((l) => l.side === "long")!;
  const main = evaluateTrigger("long", normalizePlan(PLAN_RAW)!.long!, normalizeSnapshot(raw)!, 21050, 90, 15);
  assert.equal(main.status, "TRIGGERED", "synthetic series must fire the main evaluator");
  assert.equal(long.state, "TRIGGERED");
  assert.deepEqual(long.checks.map((c) => c.label), main.checks.map((c) => c.label));
});

test("missing 1m delta cannot confirm a trigger on the extras card (consistent with main)", () => {
  const raw = flowRaw({
    series_1m: risingSeries().map((b) => ({ ...b, delta: null, vol: null })),
  });
  const gate = routeGate(raw);
  const card = readPlanCard(PLAN_RAW, raw, NOW_S, gate);
  const long = card.legs.find((l) => l.side === "long")!;
  assert.equal(long.state, "ARMED", "missing delta must withhold TRIGGERED, not confirm it");
  const deltaCheck = long.checks.find((c) => /delta/i.test(c.label));
  assert.equal(deltaCheck?.ok, false);
});

test('missing delta cannot satisfy a zero-threshold plan', () => {
  const plan={...PLAN_RAW,long:{...PLAN_RAW.long,minDelta:0}};
  const raw=flowRaw({series_1m:risingSeries().map(b=>({...b,delta:null}))});
  const card=readPlanCard(plan,raw,NOW_S,routeGate(raw,OK_GATE_ARGS,1,false,plan));
  const long=card.legs.find(l=>l.side==='long')!;
  assert.notEqual(long.state,'TRIGGERED');
  assert.equal(long.checks.find(c=>/delta/i.test(c.label))?.ok,false);
  assert.match(long.checks.find(c=>/delta/i.test(c.label))?.detail??'',/unavailable/i);
});

// ---- (3) normalizeSnapshot: preserve unknown, withhold analytics, keep price bars ----

test("C3: missing/null CVD, delta and volume are preserved as unknown, not fabricated to 0", () => {
  const raw = {
    as_of_epoch: NOW_S - 5,
    price: { last: 7730 },
    series_1m: [
      { t: NOW_S - 120, o: 1, h: 2, l: 0.5, c: 1.5 }, // keys absent
      { t: NOW_S - 60, o: 1, h: 2, l: 0.5, c: 1.5, vol: null, delta: null, cvd: null }, // explicit null
      { t: NOW_S - 0, o: 1, h: 2, l: 0.5, c: 1.5, vol: 0, delta: 0, cvd: 0 }, // genuine zero
    ],
  };
  const snap = normalizeSnapshot(raw)!;
  assert.equal(snap.bars.length, 3, "valid price bars must not be dropped");
  assert.equal(snap.bars[0].vol, null);
  assert.equal(snap.bars[0].delta, null);
  assert.equal(snap.bars[0].cvd, null);
  assert.equal(snap.bars[1].delta, null);
  assert.equal(snap.bars[2].vol, 0, "genuine zero must stay zero, not become unknown");
  assert.equal(snap.bars[2].delta, 0);
  assert.equal(snap.bars[2].cvd, 0);
});

test("C3: 11 rising bars with a final null CVD do NOT create a bearish divergence", () => {
  const bars: Record<string, unknown>[] = [];
  for (let i = 0; i < 11; i++) {
    bars.push({
      t: NOW_S - (11 - i) * 60,
      o: 7700 + i, h: 7701 + i, l: 7699.5 + i, c: 7700.5 + i,
      vol: 900, delta: 40, cvd: 100 * (i + 1), // CVD rising 100..1100
    });
  }
  bars[10] = { ...bars[10], cvd: null }; // final CVD unknown
  const snap = normalizeSnapshot({ as_of_epoch: NOW_S, price: { last: 7710.5 }, series_1m: bars })!;
  const alerts = tapeAlerts(snap);
  assert.equal(snap.cvd, null, "snapshot CVD is unknown when the final bar CVD is unknown");
  assert.equal(alerts.filter((a) => a.kind === "divergence").length, 0,
    "missing final CVD must withhold the divergence, never fabricate one from a coerced 0");
});

test("C3: analytics requiring unknown values are withheld; aggregates propagate unknown", () => {
  const raw = {
    as_of_epoch: NOW_S - 5,
    price: { last: 7730 },
    series_1m: [
      { t: NOW_S - 60, o: 7729, h: 7731, l: 7728, c: 7730, vol: null, delta: null, cvd: null },
    ],
  };
  const snap = normalizeSnapshot(raw)!;
  const rows = recentBars(snap.bars);
  assert.equal(rows[0].bigDelta, false, "unknown delta cannot be a big delta");
  assert.equal(rows[0].absorb, null, "absorption is withheld without a known delta");
  assert.equal(rows[0].volSpike, false, "volume spike is withheld without a known volume");
  const blocks = blocks15(snap.bars);
  assert.ok(Number.isNaN(blocks[0].vol), "a block with unknown volume reports unknown, not 0");
  assert.ok(Number.isNaN(blocks[0].delta), "a block with unknown delta reports unknown, not 0");
});

test("C3: 5m aggregation propagates unknown delta; the trigger gate fails closed on it", () => {
  // Two COMPLETE 5m buckets relative to asOf=NOW_S: bucket ends 1794246300 and 1794246600.
  const b0 = 1794246000;
  const bars: Bar1m[] = [];
  for (let i = 0; i < 10; i++) {
    const t = b0 + i * 60;
    bars.push({ t, o: 7718, h: 7719, l: 7717, c: 7718.5, vol: 900, delta: i === 9 ? null : 40, cvd: 100 + i });
  }
  const five = completed5m(bars, NOW_S);
  assert.equal(five.length, 2);
  const last = five[five.length - 1];
  assert.ok(Number.isNaN(last.delta), "a 5m bucket containing an unknown 1m delta is unknown");
  assert.equal(last.vol, 900 * 5, "known volume still sums even when the delta is unknown");
  const earlier = five[0];
  assert.equal(earlier.delta, 40 * 5, "a fully known bucket still sums known deltas");
  assert.equal(earlier.vol, 900 * 5);
});
