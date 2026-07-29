// Process-supervision chip derivation tests (PRB-24).
//
// WHY: pm2 jlist (what pm2 believes it supervises) and a live TCP port + PID
// probe (what is actually listening) can independently disagree, and nothing
// surfaced that as a finding before this — a human had to run `pm2 jlist` AND
// hit /health AND check the port side-by-side to notice (the exact gap behind
// the 2026-07-28/29 incidents: an orphan process serving a port pm2 believed
// dead, and pm2 believing ports were up that nothing was listening on).
// `supervisionChipState()` (lib/processSupervision.ts) is the single place
// that turns the engine's `/health/full` `process_supervision` subsystem into
// a dashboard tone/value/sub — these tests lock its contract: a confirmed
// MISMATCH is the ONLY state that renders red, "unavailable" (pm2 not on
// PATH) is a neutral environment fact and must never render red, and a stale
// or offline engine read must never show a supervision result as current.
//
// Run: cd dashboard && pnpm run test:unit
//   (node --test --experimental-strip-types "tests/**/*.node.test.ts")

import { test } from "node:test";
import assert from "node:assert/strict";
import { supervisionChipState } from "../lib/processSupervision.ts";
import type { ProcessSupervisionHealth } from "../lib/api.ts";

test("offline (engine unreachable) -> unknown, regardless of payload", () => {
  const supervision: ProcessSupervisionHealth = { status: "ok" };
  const s = supervisionChipState(supervision, /* offline */ true);
  assert.equal(s.tone, "unknown");
  assert.equal(s.value, "—");
});

test("no supervision subsystem in payload (older engine) -> unknown", () => {
  const s = supervisionChipState(undefined, false);
  assert.equal(s.tone, "unknown");
  assert.equal(s.value, "—");
});

test("status=ok -> green, no sub", () => {
  const supervision: ProcessSupervisionHealth = {
    status: "ok",
    details: {
      available: true,
      supervision_ok: true,
      error: null,
      checked_at: "2026-07-29T06:00:00Z",
      apps: {
        "jarvis-engine": {
          port: 8010,
          pm2_found: true,
          pm2_status: "online",
          pm2_pid: 100,
          port_alive: true,
          actual_pid: 100,
          mismatch_reason: null,
        },
      },
    },
  };
  const s = supervisionChipState(supervision, false);
  assert.equal(s.tone, "ok");
  assert.equal(s.value, "IN SYNC");
  assert.equal(s.sub, undefined);
});

test("status=mismatch -> red (bad), sub names the mismatched app", () => {
  const supervision: ProcessSupervisionHealth = {
    status: "mismatch",
    details: {
      available: true,
      supervision_ok: false,
      error: null,
      checked_at: "2026-07-29T06:00:00Z",
      apps: {
        "jarvis-engine": {
          port: 8010,
          pm2_found: true,
          pm2_status: "online",
          pm2_pid: 100,
          port_alive: true,
          actual_pid: 100,
          mismatch_reason: null,
        },
        "jarvis-dashboard": {
          port: 3010,
          pm2_found: true,
          pm2_status: "stopped",
          pm2_pid: null,
          port_alive: true,
          actual_pid: 987654,
          mismatch_reason:
            "pm2 reports 'jarvis-dashboard' status='stopped' but port 3010 is live (actual_pid=987654) — an orphan process is serving it under pm2's back",
        },
      },
    },
  };
  const s = supervisionChipState(supervision, false);
  assert.equal(s.tone, "bad");
  assert.equal(s.value, "MISMATCH");
  assert.equal(s.sub, "jarvis-dashboard");
});

test("status=unavailable (pm2 not on PATH) -> neutral/unknown, NEVER red", () => {
  const supervision: ProcessSupervisionHealth = {
    status: "unavailable",
    error: "pm2 not found on PATH",
  };
  const s = supervisionChipState(supervision, false);
  assert.equal(s.tone, "unknown");
  assert.notEqual(s.tone, "bad");
  assert.equal(s.value, "N/A");
  assert.equal(s.sub, "pm2 unreachable");
});

test("status=error (internal exception) -> unknown, never a false green", () => {
  const supervision: ProcessSupervisionHealth = { status: "error", error: "boom" };
  const s = supervisionChipState(supervision, false);
  assert.equal(s.tone, "unknown");
  assert.notEqual(s.tone, "ok");
});

test("unexpected/future status string -> unknown, never silently green or red", () => {
  const supervision: ProcessSupervisionHealth = { status: "some-future-status" };
  const s = supervisionChipState(supervision, false);
  assert.equal(s.tone, "unknown");
});

test("mismatch with no per-app details still renders red with no sub (never throws)", () => {
  const supervision: ProcessSupervisionHealth = { status: "mismatch" };
  const s = supervisionChipState(supervision, false);
  assert.equal(s.tone, "bad");
  assert.equal(s.value, "MISMATCH");
  assert.equal(s.sub, undefined);
});

// ── INVARIANT: "bad" tone only ever occurs for a confirmed mismatch ────────
test("INVARIANT: tone='bad' implies status==='mismatch'", () => {
  const statuses: Array<ProcessSupervisionHealth["status"]> = [
    "ok",
    "mismatch",
    "unavailable",
    "error",
    undefined,
    null,
  ];
  for (const status of statuses) {
    for (const offline of [true, false]) {
      const supervision: ProcessSupervisionHealth | undefined =
        status === undefined ? undefined : { status };
      const s = supervisionChipState(supervision, offline);
      if (s.tone === "bad") {
        assert.equal(status, "mismatch", `bad tone leaked for status=${String(status)} offline=${offline}`);
        assert.equal(offline, false, "bad tone must never render while offline");
      }
    }
  }
});
