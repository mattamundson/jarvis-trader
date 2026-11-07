// Data-integrity regression tests for dashboard/lib/tape/footprint.ts
// (PR #1013 review comments 4503369536 / 4503369558 / 4503369563).
//
// 4503369536 (P1): four parallel reads (readFootprint(), readFootprint(36),
//   readCompositeProfile(), readCompositeProfile(1)) each ingested the same
//   bytes because the mutable Agg was published into `cache` before the
//   stream offset advanced -- a single 10-lot became 40. Requires per-file
//   single-flight serialization with exact-once ingest.
// 4503369558 (P2): composite TPO summed per-price set sizes across quarter
//   prices instead of taking the union of period IDs per bucket -- the same
//   half-hour touched at 100 and 100.25 counted TPO 2 instead of 1.
// 4503369563 (P2): full-filename lexical sort breaks across contract
//   rollover -- ESH7_20261215 must outrank ESZ6_202611* by date suffix.
//
// Fixture CSVs are synthetic (no production tick data is read); the tick dir
// is pinned to a temp dir BEFORE importing the module, because footprint.ts
// snapshots TAPE_TICK_DIR into TICK_DIR at import time.
//
// Run: cd dashboard && node --test --experimental-strip-types \
//   --import ./tests/_register-alias.mjs tests/tapeFootprintIntegrity.node.test.ts

import { test, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "tape-footprint-integrity-"));
process.env.TAPE_TICK_DIR = tmpDir;

// Dynamic import AFTER env pinning (first evaluation is what fixes TICK_DIR).
const fp = await import("../lib/tape/footprint.ts");

const HEADER = "ts_utc,sym,px,sz,seq,exch,side,tag\n";
function row(ts: string, px: number, sz: number, side: string): string {
  return `${ts},ES,${px.toFixed(2)},${sz},0,DEEP,${side},x\n`;
}
function file(name: string, body: string): string {
  const p = path.join(tmpDir, name);
  fs.writeFileSync(p, body);
  return p;
}

after(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

test("P1 4503369536: four parallel reads ingest one 10-lot exactly once", async () => {
  const p = file("ESZ6_20261101.csv", HEADER + row("2026-11-01T14:30:00.000Z", 6000, 10, "A"));
  try {
    const [fp1, fp36, cp4, cp1] = await Promise.all([
      fp.readFootprint(),
      fp.readFootprint(36),
      fp.readCompositeProfile(),
      fp.readCompositeProfile(1),
    ]);
    if (!fp1.ok) throw new Error("readFootprint failed: " + fp1.error);
    assert.equal(fp1.bars.length, 1);
    const ask = fp1.bars[0].levels.reduce((s, l) => s + l.ask, 0);
    assert.equal(ask, 10, "parallel reads must not multiply volume (was 40 pre-fix)");
    if (!fp36.ok) throw new Error("readFootprint(36) failed: " + fp36.error);
    const ask36 = fp36.bars[0].levels.reduce((s, l) => s + l.ask, 0);
    assert.equal(ask36, 10);
    if (!cp4.ok) throw new Error("readCompositeProfile failed");
    assert.equal(cp4.totalVol, 10);
    if (!cp1.ok) throw new Error("readCompositeProfile(1) failed");
    assert.equal(cp1.totalVol, 10);
  } finally {
    fs.rmSync(p, { force: true });
  }
});

test("repeat read does not re-ingest cached bytes", async () => {
  const p = file("ESZ6_20261031.csv", HEADER + row("2026-10-31T14:30:00.000Z", 6000, 10, "A"));
  try {
    const first = await fp.readCompositeProfile(1);
    if (!first.ok) throw new Error("first read failed");
    const second = await fp.readCompositeProfile(1);
    if (!second.ok) throw new Error("second read failed");
    assert.equal(first.totalVol, 10);
    assert.equal(second.totalVol, 10, "repeat read must not increment");
  } finally {
    fs.rmSync(p, { force: true });
  }
});

test("append counts new bytes exactly once", async () => {
  const p = file("ESZ6_20261029.csv", HEADER + row("2026-10-29T14:30:00.000Z", 6000, 10, "A"));
  try {
    const first = await fp.readCompositeProfile(1);
    if (!first.ok) throw new Error("first read failed");
    assert.equal(first.totalVol, 10);
    fs.appendFileSync(p, row("2026-10-29T14:30:05.000Z", 6000.25, 5, "B"));
    const second = await fp.readCompositeProfile(1);
    if (!second.ok) throw new Error("second read failed");
    assert.equal(second.totalVol, 15, "appended contract counted once");
    const third = await fp.readCompositeProfile(1);
    if (!third.ok) throw new Error("third read failed");
    assert.equal(third.totalVol, 15, "re-read after append must not increment again");
  } finally {
    fs.rmSync(p, { force: true });
  }
});

test("partial trailing line is buffered, completed line ingested once", async () => {
  const p = path.join(tmpDir, "ESZ6_20261028.csv");
  // No trailing newline: the row must be held as `partial`, not ingested.
  fs.writeFileSync(p, HEADER + row("2026-10-28T14:30:00.000Z", 6000, 10, "A").trimEnd());
  try {
    const r1 = await fp.readFootprint();
    if (!r1.ok) throw new Error("read 1 failed: " + r1.error);
    assert.equal(r1.bars.length, 0, "incomplete line must not be ingested");
    fs.appendFileSync(p, "\n");
    const r2 = await fp.readFootprint();
    if (!r2.ok) throw new Error("read 2 failed: " + r2.error);
    assert.equal(r2.bars.length, 1);
    assert.equal(r2.bars[0].levels.reduce((s, l) => s + l.ask, 0), 10);
  } finally {
    fs.rmSync(p, { force: true });
  }
});

test("truncation resets ingest (no stale volume)", async () => {
  const p = file(
    "ESH6_20261027.csv",
    HEADER + row("2026-10-27T14:30:00.000Z", 6000, 10, "A") + row("2026-10-27T14:31:00.000Z", 6001, 8, "B"),
  );
  try {
    const before = await fp.readCompositeProfile(1);
    if (!before.ok) throw new Error("read 1 failed");
    assert.equal(before.totalVol, 18);
    fs.writeFileSync(p, HEADER + row("2026-10-27T14:30:00.000Z", 6000, 10, "A"));
    const afterTrunc = await fp.readCompositeProfile(1);
    if (!afterTrunc.ok) throw new Error("read 2 failed");
    assert.equal(afterTrunc.totalVol, 10, "truncated file must re-ingest from scratch");
  } finally {
    fs.rmSync(p, { force: true });
  }
});

test("P2 4503369558: TPO is union of period IDs per bucket, not sum across prices", async () => {
  const p = file(
    "ESZ6_20261103.csv",
    HEADER +
      row("2026-11-03T14:30:00.000Z", 6000, 10, "A") +
      row("2026-11-03T14:30:01.000Z", 6000.25, 6, "B"),
  );
  try {
    const r = await fp.readCompositeProfile(1, 1);
    if (!r.ok) throw new Error("composite read failed");
    assert.equal(r.rows.length, 1, "6000 and 6000.25 bucket together at bucket=1");
    assert.equal(r.rows[0].vol, 16);
    assert.equal(r.rows[0].tpo, 1, "same half-hour at 100/100.25 must be TPO 1 (was 2 pre-fix)");
  } finally {
    fs.rmSync(p, { force: true });
  }
});

test("TPO unions across multiple days (distinct half-hour periods accumulate)", async () => {
  const p1 = file("ESZ6_20261104.csv", HEADER + row("2026-11-04T14:30:00.000Z", 6000, 10, "A"));
  const p2 = file("ESZ6_20261105.csv", HEADER + row("2026-11-05T14:30:00.000Z", 6000, 10, "B"));
  try {
    const r = await fp.readCompositeProfile(2, 1);
    if (!r.ok) throw new Error("composite read failed");
    assert.equal(r.rows.length, 1);
    assert.equal(r.rows[0].vol, 20);
    assert.equal(r.rows[0].tpo, 2, "two distinct days = two distinct periods");
  } finally {
    fs.rmSync(p1, { force: true });
    fs.rmSync(p2, { force: true });
  }
});

test("P2 4503369563: rollover -- newest date suffix wins, not lexical filename", async () => {
  const p1 = file("ESZ6_20261110.csv", HEADER + row("2026-11-10T14:30:00.000Z", 6000, 10, "A"));
  const p2 = file("ESH7_20261215.csv", HEADER + row("2026-12-15T14:30:00.000Z", 6010, 7, "A"));
  try {
    const r = await fp.readFootprint();
    if (!r.ok) throw new Error("readFootprint failed: " + r.error);
    assert.equal(r.file, "ESH7_20261215.csv", "ESH7_20261215 outranks ESZ6_202611* (was ESZ6 pre-fix)");
    const c1 = await fp.readCompositeProfile(1);
    if (!c1.ok) throw new Error("composite(1) failed");
    assert.equal(c1.totalVol, 7, "1-day window selects the latest-by-date file");
    const c2 = await fp.readCompositeProfile(2);
    assert.deepEqual(new Set(c2.days), new Set(["ESZ6_20261110.csv", "ESH7_20261215.csv"]), "N-day window covers both by date");
  } finally {
    fs.rmSync(p1, { force: true });
    fs.rmSync(p2, { force: true });
  }
});
