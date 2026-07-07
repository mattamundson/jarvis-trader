#!/usr/bin/env node
/**
 * durability.mjs — "how many days straight has the engine run as designed?"
 *
 * The measurement half of Task 4 (clean uninterrupted paper-run durability). It
 * reads the outage ledger that down-alert.mjs appends (down_alert_events.jsonl)
 * plus the live state file, and reports the paper stack's uptime durability:
 *
 *   - current status: CLEAN (up) or IN OUTAGE (down since T)
 *   - days clean since the last outage (the headline number)
 *   - longest clean streak on record
 *   - total outages, total downtime, mean time between failures (MTBF)
 *
 * It invents nothing: with no ledger and no outages it says "no outages recorded
 * since <monitoring start>", and if monitoring never started it says so. Every
 * number is derived from recorded events, never assumed.
 *
 *   node scripts/ops/durability.mjs            # human-readable
 *   node scripts/ops/durability.mjs --json     # machine-readable (for a widget/endpoint)
 *
 * Env (must match down-alert.mjs):
 *   DOWN_ALERT_EVENTS  (default engine/data/down_alert_events.jsonl)
 *   DOWN_ALERT_STATE   (default engine/data/down_alert_state.json)
 */

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const EVENTS_PATH =
  process.env.DOWN_ALERT_EVENTS || resolve(HERE, "../../engine/data/down_alert_events.jsonl");
const STATE_PATH =
  process.env.DOWN_ALERT_STATE || resolve(HERE, "../../engine/data/down_alert_state.json");
const JSON_OUT = process.argv.includes("--json");
const DAY_MS = 86_400_000;

function readOutages() {
  try {
    return readFileSync(EVENTS_PATH, "utf8")
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
      .map((l) => {
        try {
          return JSON.parse(l);
        } catch {
          return null;
        }
      })
      .filter((o) => o && o.downSince && o.recoveredAt)
      .sort((a, b) => Date.parse(a.recoveredAt) - Date.parse(b.recoveredAt));
  } catch {
    return [];
  }
}

function readState() {
  try {
    return JSON.parse(readFileSync(STATE_PATH, "utf8"));
  } catch {
    return null;
  }
}

function fmtDuration(ms) {
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`;
  if (ms < 3_600_000) return `${(ms / 60_000).toFixed(1)}m`;
  if (ms < DAY_MS) return `${(ms / 3_600_000).toFixed(1)}h`;
  return `${(ms / DAY_MS).toFixed(2)}d`;
}

function compute() {
  const outages = readOutages();
  const state = readState();
  const now = Date.now();

  const monitoringSince = state?.monitoringSince || outages[0]?.downSince || null;
  const currentlyDown = !!state?.downSince;

  // The current clean streak starts at the last recovery, or at monitoring start
  // if there has never been an outage. It ends now (or at the outage start if down).
  const lastRecoveredAt = outages.length ? outages[outages.length - 1].recoveredAt : null;
  const streakStartMs = lastRecoveredAt
    ? Date.parse(lastRecoveredAt)
    : monitoringSince
      ? Date.parse(monitoringSince)
      : null;
  const streakEndMs = currentlyDown ? Date.parse(state.downSince) : now;
  const currentStreakMs =
    streakStartMs != null ? Math.max(0, streakEndMs - streakStartMs) : null;

  // Longest clean streak: gaps between consecutive outages, plus the opening gap
  // (monitoring start → first outage) and the current (still-open) streak.
  let longestStreakMs = 0;
  if (monitoringSince && outages.length) {
    let prev = Date.parse(monitoringSince);
    for (const o of outages) {
      longestStreakMs = Math.max(longestStreakMs, Date.parse(o.downSince) - prev);
      prev = Date.parse(o.recoveredAt);
    }
  }
  if (currentStreakMs != null) longestStreakMs = Math.max(longestStreakMs, currentStreakMs);

  const totalDowntimeMs = outages.reduce((s, o) => s + (o.durationMs || 0), 0);
  const observedMs = monitoringSince ? now - Date.parse(monitoringSince) : 0;
  const mtbfMs = outages.length ? observedMs / outages.length : null;

  return {
    monitoringSince,
    currentlyDown,
    downSince: currentlyDown ? state.downSince : null,
    outageCount: outages.length,
    currentStreakMs,
    currentStreakDays: currentStreakMs != null ? currentStreakMs / DAY_MS : null,
    longestStreakMs: longestStreakMs || null,
    longestStreakDays: longestStreakMs ? longestStreakMs / DAY_MS : null,
    totalDowntimeMs,
    mtbfMs,
    lastOutage: outages.length ? outages[outages.length - 1] : null,
  };
}

const d = compute();

if (JSON_OUT) {
  console.log(JSON.stringify(d, null, 2));
  process.exit(0);
}

console.log("\n  Engine durability — clean-run measurement\n");
if (!d.monitoringSince) {
  console.log("  ⚪ No monitoring data yet. Wire up down-alert.mjs (see");
  console.log("     docs/runbooks/ENGINE_DOWN_ALERTING.md) and let it run.\n");
  process.exit(0);
}

if (d.currentlyDown) {
  console.log(`  🔴 IN OUTAGE — engine down since ${d.downSince}`);
} else if (d.currentStreakDays != null) {
  console.log(`  🟢 CLEAN — ${d.currentStreakDays.toFixed(2)} days straight (${fmtDuration(d.currentStreakMs)})`);
}
console.log(`     monitoring since   ${d.monitoringSince}`);
if (d.outageCount === 0) {
  console.log(`     outages recorded   0 — no outage since monitoring began`);
} else {
  console.log(`     outages recorded   ${d.outageCount}`);
  console.log(`     longest clean run  ${d.longestStreakDays.toFixed(2)}d (${fmtDuration(d.longestStreakMs)})`);
  console.log(`     total downtime     ${fmtDuration(d.totalDowntimeMs)}`);
  if (d.mtbfMs) console.log(`     MTBF               ${fmtDuration(d.mtbfMs)} between failures`);
  if (d.lastOutage)
    console.log(
      `     last outage        ${d.lastOutage.downSince} → ${d.lastOutage.recoveredAt} (${fmtDuration(d.lastOutage.durationMs)})`
    );
}
console.log("");
process.exit(0);
