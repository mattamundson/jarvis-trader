// Unit tests for the plan-of-record availability gate (lib/tapePlan::planAvailability).
// A stale, wrong-session, or conflicting plan must be reported unavailable for actionable
// triggers — the dashboard never auto-picks between plan sources.

import test from "node:test";
import assert from "node:assert/strict";
import { normalizePlan, planAvailability, type TapePlan } from "@/lib/tapePlan";

const planFrom = (raw: unknown): TapePlan | null => normalizePlan(raw);

const base = {
  date: "2026-11-09",
  note: "test",
  long: { trigger: 7725.75, minDelta: 150, targets: [7740], stop: 7709.75 },
};

test("ok when plan date matches today, globex date, recorder session and levels source", () => {
  const p = planFrom(base);
  const a = planAvailability(p, {
    todayCt: "2026-11-09",
    globexTradingDate: "2026-11-09",
    recorderSessionTradingDay: "2026-11-09",
    recorderLevelsSource: "tape-config (tape-plan dated 2026-11-09)",
  });
  assert.equal(a.usable, true);
  assert.equal(a.kind, "ok");
});

test("missing plan is unavailable", () => {
  const a = planAvailability(null, { todayCt: "2026-11-09", globexTradingDate: "2026-11-09", recorderSessionTradingDay: null, recorderLevelsSource: null });
  assert.equal(a.usable, false);
  assert.equal(a.kind, "missing_plan");
});

test("plan without a date is unavailable", () => {
  const a = planAvailability(planFrom({ ...base, date: null }), { todayCt: "2026-11-09", globexTradingDate: "2026-11-09", recorderSessionTradingDay: null, recorderLevelsSource: null });
  assert.equal(a.usable, false);
  assert.equal(a.kind, "missing_date");
});

test("stale date (audit case: plan 2026-11-03 vs today 2026-11-07) is unavailable, not auto-promoted", () => {
  const p = planFrom({ ...base, date: "2026-11-03" });
  const a = planAvailability(p, {
    todayCt: "2026-11-07",
    globexTradingDate: "2026-11-07",
    recorderSessionTradingDay: "2026-11-07",
    recorderLevelsSource: "tape-config (tape-plan dated 2026-11-06, not today 2026-11-07 CT)",
  });
  assert.equal(a.usable, false);
  assert.equal(a.kind, "stale_date");
  assert.match(a.reason, /2026-11-03/);
  assert.match(a.reason, /stale/);
});

test("wrong session: plan date matches calendar today but not the recorder's trading day", () => {
  // Monday 2026-11-09 18:00 CT: calendar today still 11-09, but the Globex session is 11-10.
  const p = planFrom(base); // dated 2026-11-09
  const a = planAvailability(p, {
    todayCt: "2026-11-09",
    globexTradingDate: "2026-11-10",
    recorderSessionTradingDay: "2026-11-10",
    recorderLevelsSource: "tape-config (tape-plan dated 2026-11-10)",
  });
  assert.equal(a.usable, false);
  assert.equal(a.kind, "wrong_session");
  assert.match(a.reason, /wrong session/);
});

test("conflicting plan sources are explicit and never auto-resolved", () => {
  const p = planFrom(base); // dashboard plan dated 2026-11-09
  const a = planAvailability(p, {
    todayCt: "2026-11-09",
    globexTradingDate: "2026-11-09",
    recorderSessionTradingDay: "2026-11-09",
    recorderLevelsSource: "tape-config (tape-plan dated 2026-11-10, not today 2026-11-09 CT)",
  });
  assert.equal(a.usable, false);
  assert.equal(a.kind, "conflict");
  assert.match(a.reason, /2026-11-10/);
  assert.match(a.reason, /not auto-resolved/);
});

test("a non-dated levels_source string does not create a false conflict", () => {
  const p = planFrom(base);
  const a = planAvailability(p, {
    todayCt: "2026-11-09",
    globexTradingDate: "2026-11-09",
    recorderSessionTradingDay: "2026-11-09",
    recorderLevelsSource: "tape-config (no dated plan loaded)",
  });
  assert.equal(a.usable, true);
  assert.equal(a.kind, "ok");
});

test("missing recorder context (nulls) still gates on date only", () => {
  const p = planFrom(base);
  const a = planAvailability(p, { todayCt: "2026-11-09", globexTradingDate: null, recorderSessionTradingDay: null, recorderLevelsSource: null });
  assert.equal(a.usable, true);
  assert.equal(a.kind, "ok");
});
