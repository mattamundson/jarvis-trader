import test from "node:test";
import assert from "node:assert/strict";
import { evaluateTrigger, ifThenText, type SidePlan } from "@/lib/tapePlan";
import type { Bar1m, TapeSnapshot } from "@/lib/tapeDerive";

// 1_700_000_100 is divisible by 300, so these buckets are 5-minute aligned.
const T0 = 1_700_000_100;
const LONG: SidePlan = { trigger: 100, minDelta: 150, targets: [110], stop: 90 };
const SHORT: SidePlan = { trigger: 100, minDelta: 150, targets: [90], stop: 110 };

function minutes(start: number, close: number, delta = 200, low = close - 0.25): Bar1m[] {
  const out: Bar1m[] = [];
  for (let i = 0; i < 5; i++) {
    out.push({ t: start + i * 60, o: close, h: close + 0.5, l: low, c: close, vol: 100, delta, cvd: 10 });
  }
  return out;
}

function snap(bars: Bar1m[], asOf: number, last: number, nq = 21061): TapeSnapshot {
  return {
    asOfEpoch: asOf,
    asOfCt: null,
    price: { last, hi: last + 1, lo: last - 1, vwap: last },
    cvd: 10,
    nq: { last: nq, lead: null, windows: {} },
    levels: [],
    bars,
  };
}

function longEval(bars: Bar1m[], asOf: number, last = 102) {
  return evaluateTrigger("long", LONG, snap(bars, asOf, last), 21000, 90, 15);
}

test("one 5m close beyond the level does not confirm, even with delta and NQ", () => {
  const bars = [...minutes(T0, 99), ...minutes(T0 + 300, 101)];
  const ev = longEval(bars, T0 + 600);
  assert.equal(ev.status, "ARMED");
  assert.equal(ev.checks[0].ok, false);
  assert.match(ev.checks[0].label, /^two consecutive 5m closes above 100$/);
  assert.match(ev.checks[0].detail, /1 of 2/);
  assert.match(ifThenText("long", LONG, 21000), /two consecutive 5m closes above 100/);
});

test("two consecutive 5m closes beyond the level confirm the long and the short", () => {
  const longBars = [...minutes(T0, 101), ...minutes(T0 + 300, 102)];
  const long = longEval(longBars, T0 + 600);
  assert.equal(long.status, "TRIGGERED");
  assert.equal(long.checks[0].ok, true);
  assert.match(long.reason, /two-close/);

  const shortBars = [...minutes(T0, 99, -200), ...minutes(T0 + 300, 98, -200)];
  const short = evaluateTrigger("short", SHORT, snap(shortBars, T0 + 600, 98, 20900), 21000, 90, 15);
  assert.equal(short.status, "TRIGGERED");
  assert.equal(short.checks[0].ok, true);
  assert.match(short.checks[0].label, /two consecutive 5m closes below 100/);
});

test("two beyond closes with a gap between them do not confirm", () => {
  const bars = [...minutes(T0, 101), ...minutes(T0 + 600, 102)];
  const ev = longEval(bars, T0 + 900);
  assert.equal(ev.status, "ARMED");
  assert.equal(ev.checks[0].ok, false);
});

test("a close back through the level after two confirming closes is a failure, not a fill", () => {
  const bars = [...minutes(T0, 101), ...minutes(T0 + 300, 102), ...minutes(T0 + 600, 99)];
  const ev = longEval(bars, T0 + 900, 99);
  assert.equal(ev.status, "FAILED");
  assert.match(ev.reason, /two confirming closes/);
  assert.equal(ev.status === "TRIGGERED", false);
});

test("the confirming bar cannot wick through the stop and still signal", () => {
  const bars = [...minutes(T0, 101), ...minutes(T0 + 300, 102, 200, 89)];
  const ev = longEval(bars, T0 + 600);
  assert.notEqual(ev.status, "TRIGGERED");
  assert.equal(ev.checks[0].ok, false);
});
