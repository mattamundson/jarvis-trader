import { test } from "node:test";
import assert from "node:assert/strict";
import { maskAccountIds, maskDeep, maskId } from "../lib/ops/mask.ts";
import { ctDate, parseJournal, parseLadder, parseLockout, parseScoredCsv, parseStrikeLog } from "../lib/ops/parse.ts";
import { buildOpsSnapshot } from "../lib/ops/snapshot.ts";
import { CHECKLIST, JOURNAL, STRIKES, TRACKER } from "./opsFixtures.ts";

const NOW = new Date("2026-10-27T15:00:00Z"); // Tue 10:00 CDT

test("mask: ids are reduced to the last 4, already-masked and date-like values are left alone", () => {
  assert.equal(maskId("U1234567"), "••••4567");
  assert.equal(maskAccountIds("IBKR DU1234567 and U7654321"), "IBKR ••••4567 and ••••4321");
  assert.equal(maskAccountIds("acct 12345 / account #99887766"), "acct ••••2345 / account #••••7766");
  assert.equal(maskAccountIds("policy PA-1234567"), "policy ••••4567");
  assert.equal(maskAccountIds("4111 1111 1111 1111"), "••••1111");
  assert.equal(maskAccountIds("Robinhood ••1804 and •••7225"), "Robinhood ••1804 and •••7225");
  assert.equal(maskAccountIds("SPXW 7735C 10/27 stop 7725.5, 20261027"), "SPXW 7735C 10/27 stop 7725.5, 20261027");
});

test("mask: maskDeep reaches nested strings and arrays, leaves numbers", () => {
  const out = maskDeep({ a: ["DU1234567", { b: "acct 55512345" }], n: 5, ok: true, z: null });
  assert.deepEqual(out, { a: ["••••4567", { b: "acct ••••2345" }], n: 5, ok: true, z: null });
});

test("ladder: clean sessions, scored setups and avg R come from the Current state table", () => {
  const { ladder, recentSessions, unlock } = parseLadder(TRACKER);
  assert.deepEqual(ladder.cleanSessions, { done: 10, target: 10 });
  assert.deepEqual(ladder.runningClean, { n: 12, of: 20 });
  assert.deepEqual(ladder.scored, { n: 6, of: 20, avgR: 0.2 });
  assert.equal(ladder.strikes30d, 17);
  assert.equal(ladder.sessionLogThrough, "2026-10-23");
  assert.match(ladder.liveStatus ?? "", /^ILLEGAL/);
  assert.deepEqual(recentSessions.map((r) => [r.date, r.verdict]), [["2026-10-22", "unknown"], ["2026-10-21", "clean"], ["2026-10-20", "not clean"]]);
  assert.deepEqual(unlock.map((u) => u.done), [true, false]);
});

test("ladder: negative avg R with a unicode minus parses; missing fields are null, not guessed", () => {
  const md = "## Current state\n| Field | Value |\n|---|---|\n| Scored paper setups | **3/20 scored setups, avg R = −0.40** |\n";
  const { ladder } = parseLadder(md);
  assert.deepEqual(ladder.scored, { n: 3, of: 20, avgR: -0.4 });
  assert.equal(ladder.cleanSessions, null);
  assert.equal(ladder.runningClean, null);
  assert.equal(parseLadder("nothing here").ladder.scored, null);
});

test("strike log: confirmed, pending, count and the lockout window", () => {
  const k = parseStrikeLog(STRIKES);
  assert.equal(k.confirmed.length, 2);
  assert.equal(k.confirmed[0].date, "2026-10-19");
  assert.equal(k.pending.length, 1);
  assert.equal(k.pending[0].status, "pending");
  assert.equal(k.confirmedCount, 17);
  assert.equal(k.countUpdated, "2026-10-26");
  assert.deepEqual(k.window, { state: "ACTIVE", from: "2026-10-21", to: "2026-10-27" });
});

test("lockout: ON inside the window, still ON after it until a release record exists", () => {
  const k = parseStrikeLog(STRIKES);
  const l = parseLaddered();
  const inside = parseLockout(k, CHECKLIST, l, NOW);
  assert.equal(inside.on, true);
  assert.equal(inside.strikeWindow?.phase, "in-window");
  assert.equal(inside.weeklyUnreleased, true);
  assert.equal(inside.releaseRecords, 0);
  assert.deepEqual(inside.conditions.map((c) => c.done), [false, true]);

  const after = parseLockout(k, CHECKLIST, l, new Date("2026-10-29T15:00:00Z"));
  assert.equal(after.strikeWindow?.phase, "after");
  assert.equal(after.on, true, "an expired window does not lift the weekly lockout; only Matt's yes does");
  assert.match(after.summary, /needs the checklist and Matt's written yes/);

  const unknown = parseLockout(null, null, null, NOW);
  assert.equal(unknown.on, true, "unknown is treated as ON");
});

function parseLaddered() { return parseLadder(TRACKER).ladder; }

test("ctDate is DST aware around 2026-11-01", () => {
  assert.equal(ctDate(new Date("2026-11-01T04:30:00Z")), "2026-10-31"); // 23:30 CDT
  assert.equal(ctDate(new Date("2026-11-01T05:30:00Z")), "2026-11-01");
  assert.equal(ctDate(new Date("2026-11-02T05:30:00Z")), "2026-11-01"); // 23:30 CST
  assert.equal(ctDate(new Date("2026-11-02T06:30:00Z")), "2026-11-02");
});

test("journal: both table layouts parse by header name, newest first", () => {
  const j = parseJournal(JOURNAL);
  assert.equal(j.total, 2);
  assert.equal(j.liveReviews, 1);
  assert.equal(j.lastDate, "2026-10-26");
  assert.equal(j.recent[0].date, "2026-10-26");
  assert.equal(j.recent[0].rResult, "−2.91R realized");
  assert.equal(j.recent[1].rResult, "+1.2R target");
  assert.equal(j.recent[0].live, true);
});

test("scored csv: header only is 0 rows, rows average the R column", () => {
  assert.deepEqual(parseScoredCsv("date,setup,R\n"), { rows: 0, avgR: null });
  const c = parseScoredCsv("date,setup,R\n2026-10-01,a,1\n2026-10-02,b,−0.5\n");
  assert.equal(c.rows, 2);
  assert.equal(c.avgR, 0.25);
});

test("snapshot: every string is masked, gaps and mismatches are reported, stance is fixed", () => {
  const texts = { tracker: TRACKER, strikeLog: STRIKES, lockout: CHECKLIST, journal: JOURNAL, scoredCsv: "date,R\n" };
  const meta = Object.fromEntries(Object.keys(texts).map((k) => [k, { bytes: 10, mtimeMs: NOW.getTime() - 3_600_000 }]));
  const s = buildOpsSnapshot(texts, meta, NOW, "tape/hermes");
  const json = JSON.stringify(s);
  for (const raw of ["U1234567", "DU1234567", "DU7654321", "12345678"]) assert.ok(!json.includes(raw), `unmasked ${raw}`);
  assert.ok(json.includes("••••4567") && json.includes("••1804"));
  assert.equal(s.liveLegal, "NO");
  assert.equal(s.size, 0);
  assert.ok(s.warnings.some((w) => /scored-setups\.csv has 0 rows/.test(w)));
  assert.ok(s.warnings.some((w) => /1 strike\(s\) pending/.test(w)));

  const empty = buildOpsSnapshot({}, {}, NOW, null);
  assert.equal(empty.ladder, null);
  assert.equal(empty.lockout?.on, true);
  assert.equal(empty.warnings.length, 5);
});

test("snapshot: stale files are flagged after 36h", () => {
  const s = buildOpsSnapshot({ tracker: TRACKER }, { tracker: { bytes: 1, mtimeMs: NOW.getTime() - 50 * 3_600_000 } }, NOW, "x/y");
  assert.equal(s.files.find((f) => f.key === "tracker")?.stale, true);
  assert.ok(s.warnings.some((w) => /50h old/.test(w)));
});
