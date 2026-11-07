// Unit tests for the explicit known-market-state contract (lib/marketSession).
// Closure is asserted ONLY from the CME ES Globex weekly schedule
// (Sun 17:00 CT - Fri 16:00 CT, daily break 16:00-17:00 CT), never from recorder idleness.
// November 2026 is CST (UTC-6), so CT wall time = UTC - 6h.

import test from "node:test";
import assert from "node:assert/strict";
import { currentGlobexTradingDate, esMarketState, ES_SCHEDULE_BASIS } from "@/lib/marketSession";

/** CT wall-clock -> epoch ms (CST, UTC-6). */
const atCt = (y: number, m: number, d: number, hh: number, mm: number) => Date.UTC(y, m - 1, d, hh + 6, mm, 0);

test("Saturday early morning is scheduled_closed with a schedule basis", () => {
  const s = esMarketState(atCt(2026, 11, 7, 1, 47)); // audit time, Sat
  assert.equal(s.state, "scheduled_closed");
  assert.equal(s.basis, "cme-globex-schedule");
  assert.match(s.detail, /Saturday/);
});

test("Friday before 16:00 CT is scheduled_open; after is closed", () => {
  assert.equal(esMarketState(atCt(2026, 11, 6, 15, 0)).state, "scheduled_open");
  assert.equal(esMarketState(atCt(2026, 11, 6, 16, 30)).state, "scheduled_closed");
  assert.match(esMarketState(atCt(2026, 11, 6, 16, 30)).detail, /Friday 16:00/);
});

test("Mon-Thu daily maintenance break 16:00-17:00 CT is closed", () => {
  assert.equal(esMarketState(atCt(2026, 11, 9, 16, 30)).state, "scheduled_closed");
  assert.match(esMarketState(atCt(2026, 11, 9, 16, 30)).detail, /maintenance/);
  assert.equal(esMarketState(atCt(2026, 11, 9, 12, 0)).state, "scheduled_open");
  assert.equal(esMarketState(atCt(2026, 11, 10, 17, 0)).state, "scheduled_open"); // 17:00 reopens
});

test("Sunday before 17:00 closed; Sunday evening open", () => {
  assert.equal(esMarketState(atCt(2026, 11, 8, 10, 0)).state, "scheduled_closed");
  assert.equal(esMarketState(atCt(2026, 11, 8, 18, 0)).state, "scheduled_open");
  assert.match(esMarketState(atCt(2026, 11, 8, 18, 0)).detail, /Sunday evening/);
});

test("boundary minutes: 16:59:59-ish still closed on Mon-Thu, 15:59 open on Friday", () => {
  assert.equal(esMarketState(atCt(2026, 11, 9, 16, 59)).state, "scheduled_closed");
  assert.equal(esMarketState(atCt(2026, 11, 6, 15, 59)).state, "scheduled_open");
});

test("open-window detail never asserts closure from idleness and carries the basis text", () => {
  const s = esMarketState(atCt(2026, 11, 9, 12, 0));
  assert.equal(s.state, "scheduled_open");
  assert.ok(!/idle/i.test(s.detail));
  assert.ok(s.detail.includes("holidays not accounted"));
});

test("non-finite clock yields unknown, never an assertion", () => {
  const s = esMarketState(Number.NaN);
  assert.equal(s.state, "unknown");
});

test("Globex trading date rolls to next calendar day at 17:00 CT", () => {
  assert.equal(currentGlobexTradingDate(atCt(2026, 11, 9, 12, 0)), "2026-11-09");
  assert.equal(currentGlobexTradingDate(atCt(2026, 11, 9, 18, 0)), "2026-11-10"); // Monday evening = Tuesday's session
  assert.equal(currentGlobexTradingDate(atCt(2026, 11, 8, 18, 0)), "2026-11-09"); // Sunday evening = Monday's session
  assert.equal(currentGlobexTradingDate(atCt(2026, 11, 7, 1, 47)), "2026-11-07"); // Saturday early = same calendar date
  assert.equal(currentGlobexTradingDate(Number.NaN), null);
});

test("schedule basis constant names the CME source and its limits", () => {
  assert.match(ES_SCHEDULE_BASIS, /CME/);
  assert.match(ES_SCHEDULE_BASIS, /Sun 17:00/);
  assert.match(ES_SCHEDULE_BASIS, /Fri 16:00/);
  assert.match(ES_SCHEDULE_BASIS, /holidays not accounted/);
});
