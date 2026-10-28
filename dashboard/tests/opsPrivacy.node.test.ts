import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { decideOpsAccess, isLocalHost } from "../lib/ops/guard.ts";
import { isPublicReadOnlyPath } from "../lib/publicRoutes.ts";
import { decideDashboardAuth } from "../lib/dashboardAuth.ts";
import { buildOpsSnapshot } from "../lib/ops/snapshot.ts";
import { CHECKLIST, JOURNAL, STRIKES, TRACKER } from "./opsFixtures.ts";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (rel: string) => readFileSync(path.join(ROOT, rel), "utf8");
function walk(rel: string): string[] {
  const abs = path.join(ROOT, rel);
  try { statSync(abs); } catch { return []; }
  if (statSync(abs).isFile()) return [rel];
  return readdirSync(abs).flatMap((n) => walk(path.join(rel, n)));
}

test("/ops and /api/ops are not public paths, so middleware Basic Auth covers them", () => {
  for (const p of ["/ops", "/ops/", "/ops/anything", "/api/ops", "/api/ops/ladder", "/OPS"]) {
    assert.equal(isPublicReadOnlyPath(p), false, p);
  }
  // sanity: the real public paths are still public, so the check above is not vacuous
  assert.equal(isPublicReadOnlyPath("/market-brief-public"), true);
});

test("middleware matcher covers /ops (nothing excludes it from auth)", () => {
  const src = read("middleware.ts");
  const m = src.match(/matcher:\s*\["([^"]+)"\]/);
  assert.ok(m, "matcher found");
  // Next matcher "/((?!a|b).*)" as a regex
  const re = new RegExp("^" + m![1].replace(/favicon\.ico/, "favicon\\.ico") + "$");
  assert.ok(re.test("/ops") && re.test("/api/ops"), "matcher applies to /ops and /api/ops");
  assert.ok(!re.test("/_next/static/x"), "matcher still skips static assets (so the regex is real)");
  assert.match(src, /isPublicReadOnlyRequest\(req\.nextUrl\.pathname, req\.method\)/);
});

test("auth policy: hosted without credentials is denied, credentials are enforced", () => {
  assert.equal(decideDashboardAuth({ vercel: "1" }), "deny");
  assert.equal(decideDashboardAuth({ user: "u", pass: "p" }), "enforce");
});

test("ops guard: hosted and remote-without-credentials are refused; localhost and credentialed are allowed", () => {
  assert.equal(decideOpsAccess({ host: "localhost:3010" }).allowed, true);
  assert.equal(decideOpsAccess({ host: "127.0.0.1:3077" }).allowed, true);
  assert.equal(decideOpsAccess({ host: "[::1]:3010" }).allowed, true);
  assert.deepEqual(decideOpsAccess({ host: "abc.trycloudflare.com" }), { allowed: false, reason: "remote-without-auth" });
  assert.equal(decideOpsAccess({ host: "192.168.1.20:3010" }).allowed, false);
  assert.equal(decideOpsAccess({ host: null }).allowed, false);
  assert.equal(decideOpsAccess({ host: "localhost.evil.com" }).allowed, false);
  assert.equal(decideOpsAccess({ host: "dash.example.com", user: "u", pass: "p" }).allowed, true);
  assert.equal(decideOpsAccess({ host: "dash.example.com", user: "u" }).allowed, false);
  assert.equal(decideOpsAccess({ host: "localhost", vercel: "1" }).reason, "hosted");
  assert.equal(decideOpsAccess({ host: "localhost", user: "u", pass: "p", vercel: "1" }).allowed, false);
  assert.equal(decideOpsAccess({ host: "localhost", opsDisabled: "1" }).allowed, false);
  assert.equal(isLocalHost("LOCALHOST:80"), true);
});

// lib/tape lives in a separate in-flight lane and may not be in this checkout yet. These two tests skip loudly
// (node:test reports them as skipped, never as passed) until it lands; they must be green before /ops is merged.
const HAS_TAPE = existsSync(path.join(ROOT, "lib/tape/serialize.ts"));
const TAPE_SKIP = HAS_TAPE ? false : "lib/tape/serialize.ts is not in this checkout yet";

test("/api/tape never serializes ops data: planted ops values in every position do not survive buildTapePayload", { skip: TAPE_SKIP }, async () => {
  const { buildTapePayload } = await import("../lib/tape/serialize.ts");
  const snap = buildOpsSnapshot({ tracker: TRACKER, strikeLog: STRIKES, lockout: CHECKLIST, journal: JOURNAL }, {}, new Date("2026-10-27T15:00:00Z"), "tape/hermes");
  const planted = {
    ops: snap, hermes: snap.ladder, ladder: snap.ladder, strikes: snap.strikes, lockout: snap.lockout, journal: snap.journal,
    strike_log: "Live 0DTE options while blocked", clean_sessions: "10 / 10", scored_setups: "6/20 avg R = +0.20", acct: "DU1234567",
  };
  const raw = {
    as_of_epoch: 1_790_000_000, interval_s: 5, session: { trading_day: "2026-10-27", since_ct: "x", trades: 1, lots: 1, ...planted },
    recorder: { state: "recording", heartbeat_age_s: 3, last_tick_age_s: 7, reconnects: 0, ...planted },
    price: { last: 7724.75, bid: 7724.5, ask: 7724.75, vwap: 7724.8, hi: 7725.5, lo: 7724, ...planted },
    cvd: { value: -26, since_ct: "x", ...planted }, legs: [], levels: [], trigger: null, series_1m: [], ...planted,
  };
  const payload = buildTapePayload({ flow: raw, gex: { ...planted }, doublewide: { ...planted }, aaron: { ...planted }, gates: null }, 1_790_000_005_000);
  const json = JSON.stringify(payload);
  // gates.lockout is a deliberate single boolean the tape serializer allows (Hermes gates footer); the ops detail behind it must never appear.
  for (const needle of [
    "strike", "5-day strike lockout", "weekly 3R", "journal", "ladder", "Hermes", "hermes", "clean_sessions", "scored", "avg R", "DU1234567", "••••4567", "1804",
    "while blocked", "Not clean", "Robinhood", "paper-journal", "rebuild-ladder", "\"ops\"",
  ]) {
    assert.ok(!json.includes(needle), `/api/tape payload contains ops data: ${needle}`);
  }
});

test("tape code never imports ops code", { skip: TAPE_SKIP }, () => {
  const tapeFiles = [...walk("app/api/tape"), ...walk("app/tape"), ...walk("lib/tape"), ...walk("components/tape")];
  assert.ok(tapeFiles.length >= 5, "tape files found");
  for (const f of tapeFiles) {
    const src = read(f);
    assert.ok(!/lib\/ops|components\/ops|app\/ops|OPS_HERMES_DIR|rebuild-ladder-tracker|strike-log|paper-journal/.test(src), `${f} references ops code or Hermes ops files`);
  }
});

test("ops code never imports tape code", () => {
  const opsFiles = [...walk("lib/ops"), ...walk("components/ops"), ...walk("app/ops")];
  assert.ok(opsFiles.length >= 8, "ops files found");
  for (const f of opsFiles) {
    assert.ok(!/lib\/tape|components\/tape|api\/tape/.test(read(f)), `${f} imports tape code`);
  }
});

test("ops code is server-side only: no client directive, no fetch, no write or network calls", () => {
  for (const f of [...walk("lib/ops"), ...walk("components/ops"), ...walk("app/ops")]) {
    const src = read(f);
    assert.ok(!/["']use client["']/.test(src), `${f} is a client component`);
    assert.ok(!/\bfetch\(|XMLHttpRequest|WebSocket|writeFile|appendFile|unlink|rmSync|child_process|spawn\(|exec\(/.test(src), `${f} has a write/network/exec call`);
  }
  assert.equal(walk("app/api/ops").length, 0, "no /api/ops route exists");
});
