import { test } from "node:test";
import assert from "node:assert/strict";
import { buildTapePayload, findPrivateKeys, serializeGates } from "../lib/tape/serialize.ts";
import { ctWallToEpochMs, freshnessLevel } from "../lib/tape/time.ts";

const flowRaw = {
  as_of_epoch: 1_790_000_000, interval_s: 5, live_legal: true, size: 3,
  session: { trading_day: "2026-10-27", since_ct: "2026-10-26T23:18:16-05:00", trades: 173, lots: 410, file: "C:\\secret\\path.csv" },
  recorder: { state: "recording", heartbeat_age_s: 3, last_tick_age_s: 7, reconnects: 0, connected_port: 4001 },
  basis: { label: "bid/ask", bidask_pct: 99.4, bidask_trades: 172 },
  price: { last: 7724.75, bid: 7724.5, ask: 7724.75, vwap: 7724.8, hi: 7725.5, lo: 7724, account: "DU123" },
  cvd: { value: -26, since_ct: "x" },
  gate_cvd: { level: 540, cvd: -26, side: "below", dist: -566, label: "CVD gate", note: "n", last_cross_t: null, last_cross_ct: null },
  series_1m: [{ t: 60, o: 1, h: 2, l: 1, c: 2, vol: 3, delta: 1, cvd: 1, unrealized_pnl: 99 }],
  legs: [], lots_per_min: { last: 1, avg5: 1, avg30: 1, peak: 2 }, levels: [], trigger: null, bias: { label: "MIXED", votes: [], rule: "r" },
  nq: { status: "ok", rel: null, series: [], as_of_epoch: 1_790_000_000, interval_s: 60 },
  positions: [{ symbol: "ES", qty: 2 }], account: { equity: 123456 }, pnl: 500,
};

test("serializer rebuilds from an allow-list: unknown / private fields never survive", () => {
  const p = buildTapePayload({ flow: flowRaw, gex: null, doublewide: null, aaron: null, gates: null }, 1_790_000_005_000);
  const json = JSON.stringify(p);
  for (const leak of ["positions", "account", "equity", "pnl", "DU123", "secret", "connected_port", "bidask_trades", "unrealized"]) {
    assert.ok(!json.toLowerCase().includes(leak.toLowerCase()), `leaked ${leak}`);
  }
  assert.equal(p.live_legal, false);
  assert.equal(p.size, 0);
  assert.equal(p.flow.data?.price.last, 7724.75);
  assert.equal(p.flow.as_of_ms, 1_790_000_000_000);
  assert.deepEqual(findPrivateKeys(p), []);
});

test("strings carrying $ or P&L wording are rejected centrally", () => {
  const raw = { ...flowRaw, gate_cvd: { ...flowRaw.gate_cvd, note: "made $500 today", label: "total P&L gate" } };
  const p = buildTapePayload({ flow: raw, gex: null, doublewide: null, aaron: null, gates: null }, 0);
  assert.equal(p.flow.data?.gate_cvd.note, null);
  assert.equal(p.flow.data?.gate_cvd.label, null);
});

test("findPrivateKeys catches private-looking keys and strings", () => {
  assert.ok(findPrivateKeys({ a: { positions: [] } }).length > 0);
  assert.ok(findPrivateKeys({ a: [{ equity: 1 }] }).length > 0);
  assert.ok(findPrivateKeys({ note: "+$40" }).length > 0);
  assert.deepEqual(findPrivateKeys({ price: { last: 1 }, levels: [{ name: "x" }] }), []);
});

test("missing sources degrade to explicit empty envelopes, not fabricated data", () => {
  const p = buildTapePayload({ flow: null, gex: undefined, doublewide: "garbage", aaron: 7, gates: null }, 5);
  for (const k of ["flow", "gex", "doublewide", "aaron"] as const) {
    assert.equal(p[k].present, false);
    assert.equal(p[k].data, null);
    assert.equal(p[k].as_of_ms, null);
  }
  assert.deepEqual(p.gates, { found: false, lockout: null, gates: [] });
});

test("GEX / level sources use the SOURCE timestamp, seed flag survives", () => {
  const p = buildTapePayload({
    flow: null,
    gex: { asof_ct: "2026-10-26 14:59", spot: 7713, flip: 7777, pulled_ct: "2026-10-26 16:05", net_gex: "-34.60B", history_today: [{ asof_ct: "2026-10-26 11:04", flip: 1, pin: 2, put_wall: 3, extra: 1 }] },
    doublewide: { as_of_ct: "2026-10-26 14:50", seed: true, levels: [{ name: "DW floor", px: 7648, px2: 7660, secret: 1 }] },
    aaron: null, gates: null,
  }, 0);
  assert.equal(p.gex.as_of_ms, ctWallToEpochMs("2026-10-26 14:59"));
  assert.equal(p.gex.as_of_ms, Date.UTC(2026, 9, 26, 19, 59)); // CDT = UTC-5
  assert.equal(p.doublewide.seed, true);
  assert.deepEqual(Object.keys(p.doublewide.data!.levels![0]).sort(), ["name", "note", "px", "px2"]);
});

test("CT conversion respects DST", () => {
  assert.equal(ctWallToEpochMs("2026-01-15 12:00"), Date.UTC(2026, 0, 15, 18, 0)); // CST UTC-6
  assert.equal(ctWallToEpochMs("2026-07-15 12:00"), Date.UTC(2026, 6, 15, 17, 0)); // CDT UTC-5
  assert.equal(ctWallToEpochMs("nope"), null);
});

test("freshness thresholds: amber at 2x, red at 5x of the source's own interval", () => {
  assert.equal(freshnessLevel(9, 5), "fresh");
  assert.equal(freshnessLevel(10, 5), "amber");
  assert.equal(freshnessLevel(24, 5), "amber");
  assert.equal(freshnessLevel(25, 5), "red");
  assert.equal(freshnessLevel(null, 5), "unknown");
});

test("hermes gates footer keeps names + status only, drops R-multiple / dollar gates", () => {
  const g = serializeGates({
    found: true, fileLockout: false, message: "m",
    gates: [{ name: "One plan per day", status: "pass" }, { name: "Daily stop 2R", status: "fail" }, { name: "Max loss $200", status: "pass" }, { name: "x", status: "bogus", pnl: 1 }],
  });
  assert.deepEqual(g.gates.map((x) => x.name), ["One plan per day", "x"]);
  assert.equal(g.gates[1].status, "unknown");
  assert.equal(g.lockout, false);
});
