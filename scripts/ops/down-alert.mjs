#!/usr/bin/env node
/**
 * down-alert.mjs — OUT-OF-PROCESS down-alerting for the trading engine.
 *
 * Why this exists (and why it is not the in-process monitors):
 *   engine/monitoring/predictive_maintenance.py and engine/notifications/discord_notifier.py
 *   run INSIDE the engine. When the engine is fully DOWN (crash, port dead, OOM-kill,
 *   machine hang) those monitors are dead too and cannot alert — the exact moment you most
 *   need to know. This script runs SEPARATELY (cron / a second PM2 app / Task Scheduler),
 *   pings the engine from the outside, and fires a Discord alert when it cannot be reached.
 *
 * It reuses the engine's own DISCORD_WEBHOOK_URL and payload shape, so there is ZERO new
 * config: if the engine can post to Discord, so can this.
 *
 * Behavior (edge-triggered — will not spam):
 *   - Pings ENGINE_URL/health (auth-exempt) with a timeout.
 *   - Tracks CONSECUTIVE failures in a sidecar JSON file.
 *   - Sends ONE "engine DOWN" alert when failures first reach FAIL_THRESHOLD.
 *   - Sends ONE "engine RECOVERED" alert on the first success after an alert.
 *   - Stays silent otherwise (healthy pings, and repeated failures within the same outage).
 *
 * Run it on a schedule (the schedule sets the cadence; this script does ONE check per call):
 *   cron:            * * * * * node /path/scripts/ops/down-alert.mjs   >> down-alert.log 2>&1
 *   PM2 (cron_restart): see docs/runbooks/ENGINE_DOWN_ALERTING.md
 *   Windows Task Scheduler: every 1-2 min, action = node down-alert.mjs
 *
 * Env:
 *   ENGINE_URL           (default http://localhost:8010)  — or ENGINE_INTERNAL_URL
 *   DISCORD_WEBHOOK_URL  (required to actually send; without it the script just logs)
 *   DOWN_ALERT_STATE     (default <this dir>/../../engine/data/down_alert_state.json)
 *   DOWN_ALERT_THRESHOLD (default 2)   — consecutive failures before alerting
 *   DOWN_ALERT_TIMEOUT_MS(default 8000)
 *
 * Exit code: 0 when the engine is healthy, 1 when it is DOWN (for cron log / chaining).
 * This judges REACHABILITY only (is the engine up), not data correctness — for the IB
 * data leg see scripts/check-ib-data-watchdog.ps1; for degradation see predictive_maintenance.py.
 */

import { readFileSync, writeFileSync, mkdirSync, appendFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ENGINE =
  process.env.ENGINE_URL || process.env.ENGINE_INTERNAL_URL || "http://localhost:8010";
const WEBHOOK = (process.env.DISCORD_WEBHOOK_URL || "").trim();
const STATE_PATH =
  process.env.DOWN_ALERT_STATE || resolve(HERE, "../../engine/data/down_alert_state.json");
// Append-only ledger of completed outages, consumed by durability.mjs to compute
// "days clean since last outage". One JSON object per line (JSONL).
const EVENTS_PATH =
  process.env.DOWN_ALERT_EVENTS || resolve(HERE, "../../engine/data/down_alert_events.jsonl");
const THRESHOLD = Math.max(1, parseInt(process.env.DOWN_ALERT_THRESHOLD || "2", 10));
const TIMEOUT_MS = parseInt(process.env.DOWN_ALERT_TIMEOUT_MS || "8000", 10);

function nowIso() {
  // Date.now via new Date() is fine here (real CLI, not a workflow sandbox).
  return new Date().toISOString();
}

function loadState() {
  try {
    const s = JSON.parse(readFileSync(STATE_PATH, "utf8"));
    return {
      consecutiveFailures: s.consecutiveFailures || 0,
      alerted: !!s.alerted,
      // downSince: ISO of the first failure in the current outage (null when up).
      downSince: s.downSince || null,
      // monitoringSince: first-ever run, the baseline for the first clean streak.
      monitoringSince: s.monitoringSince || null,
    };
  } catch {
    return { consecutiveFailures: 0, alerted: false, downSince: null, monitoringSince: null };
  }
}

function saveState(state) {
  try {
    mkdirSync(dirname(STATE_PATH), { recursive: true });
    writeFileSync(STATE_PATH, JSON.stringify({ ...state, updated: nowIso() }, null, 2));
  } catch (e) {
    console.error(`[down-alert] could not write state ${STATE_PATH}: ${e.message}`);
  }
}

/** Append one completed-outage record to the JSONL ledger (durability input). */
function appendOutage(record) {
  try {
    mkdirSync(dirname(EVENTS_PATH), { recursive: true });
    appendFileSync(EVENTS_PATH, JSON.stringify(record) + "\n");
  } catch (e) {
    console.error(`[down-alert] could not append event ${EVENTS_PATH}: ${e.message}`);
  }
}

async function pingHealth() {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(ENGINE + "/health", { signal: ctrl.signal });
    if (res.status >= 500) return { ok: false, reason: `HTTP ${res.status}` };
    if (!res.ok) return { ok: false, reason: `HTTP ${res.status}` };
    return { ok: true, reason: `HTTP ${res.status}` };
  } catch (e) {
    return { ok: false, reason: e.name === "AbortError" ? "timeout" : e.cause?.code || e.message };
  } finally {
    clearTimeout(t);
  }
}

async function sendDiscord(content) {
  if (!WEBHOOK) {
    console.error("[down-alert] DISCORD_WEBHOOK_URL not set — alert NOT sent:\n" + content);
    return false;
  }
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(WEBHOOK, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ content, username: "JARVIS watchdog" }),
      signal: ctrl.signal,
    });
    if (res.status === 200 || res.status === 204) return true;
    console.error(`[down-alert] Discord webhook returned ${res.status}`);
    return false;
  } catch (e) {
    console.error(`[down-alert] Discord send failed: ${e.message}`);
    return false;
  } finally {
    clearTimeout(t);
  }
}

async function main() {
  const state = loadState();
  const { ok, reason } = await pingHealth();
  const ts = nowIso();
  // Stamp the monitoring baseline once, on the first-ever run.
  const monitoringSince = state.monitoringSince || ts;

  if (ok) {
    // Recovery edge: an outage just ended → record it to the durability ledger.
    if (state.downSince) {
      appendOutage({
        downSince: state.downSince,
        recoveredAt: ts,
        durationMs: Math.max(0, Date.parse(ts) - Date.parse(state.downSince)),
        alerted: state.alerted,
      });
    }
    if (state.alerted) {
      await sendDiscord(
        `🟢 **Engine RECOVERED** — \`${ENGINE}/health\` is responding again (${reason}) at ${ts}.`
      );
    }
    saveState({ consecutiveFailures: 0, alerted: false, downSince: null, monitoringSince });
    console.log(`[down-alert] ${ts} OK (${reason})`);
    process.exit(0);
  }

  const failures = state.consecutiveFailures + 1;
  // Outage begins at the first failed check; hold that timestamp for the whole outage.
  const downSince = state.downSince || ts;
  let alerted = state.alerted;
  if (failures >= THRESHOLD && !alerted) {
    const sent = await sendDiscord(
      `🔴 **Engine DOWN** — \`${ENGINE}/health\` unreachable (${reason}) for ${failures} ` +
        `consecutive checks as of ${ts}. Dashboard data is stale. ` +
        `Check \`pm2 status\` / \`pm2 logs jarvis-engine\`.`
    );
    alerted = alerted || sent; // only latch "alerted" if the alert actually went out
  }
  saveState({ consecutiveFailures: failures, alerted, downSince, monitoringSince });
  console.log(`[down-alert] ${ts} DOWN (${reason}) failures=${failures} alerted=${alerted}`);
  process.exit(1);
}

main();
