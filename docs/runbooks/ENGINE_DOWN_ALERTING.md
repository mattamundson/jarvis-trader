# Engine down-alerting — get pinged when the engine dies

**The problem the in-process monitors cannot solve.** `engine/monitoring/predictive_maintenance.py`
and `engine/notifications/discord_notifier.py` run *inside* the engine. When the engine is fully
**down** — crash, `pm2` crash-loop, port dead, OOM-kill, machine hang — those monitors are dead
too and stay silent. That is exactly the moment the dashboard goes stale and you want to know.

[`scripts/ops/down-alert.mjs`](../../scripts/ops/down-alert.mjs) closes that gap: it runs
**out-of-process**, pings the engine from the outside, and fires a Discord alert when it can't be
reached. It reuses the engine's own `DISCORD_WEBHOOK_URL` and payload shape — **no new config**.

## Where it fits (no overlap)

| Watchdog | Scope | Runs where | Alerts? |
|---|---|---|---|
| `predictive_maintenance.py` | Degradation (memory, latency, reconnect spikes) *before* a crash | In-process | webhook (if enabled) |
| `check-ib-data-watchdog.ps1` | IB **data leg** health (`/health/full` subsystem) | External, Windows | exit-code for overseer |
| `pm2-restart-monitor.ps1` | Restart **count** sidecar | External, Windows | no (writes JSON) |
| **`down-alert.mjs`** (this) | **Engine reachability** — is it up at all | **External, cross-platform** | **Discord** |

This one catches total death; the others catch degradation, IB-specifics, and restart counts.

## Behavior (edge-triggered — it will not spam)

- One check per invocation; the **schedule** sets the cadence.
- Pings `ENGINE_URL/health` (auth-exempt — no API key needed) with a timeout.
- Tracks **consecutive** failures in a sidecar JSON (`DOWN_ALERT_STATE`).
- Sends **one** 🔴 "Engine DOWN" alert when failures first reach `DOWN_ALERT_THRESHOLD` (default 2).
- Sends **one** 🟢 "Engine RECOVERED" alert on the first success after an alert.
- Silent otherwise (healthy pings; repeated failures inside the same outage).
- If `DISCORD_WEBHOOK_URL` is unset it logs the alert instead of sending (and keeps retrying,
  since nothing actually went out) — so a missing webhook fails loud in the log, not silent.
- Exit code: `0` healthy, `1` down.

## Env

| Var | Default | Meaning |
|---|---|---|
| `ENGINE_URL` | `http://localhost:8010` | engine base (or `ENGINE_INTERNAL_URL`) |
| `DISCORD_WEBHOOK_URL` | — | same webhook the engine uses; required to actually send |
| `DOWN_ALERT_THRESHOLD` | `2` | consecutive failures before the DOWN alert |
| `DOWN_ALERT_STATE` | `engine/data/down_alert_state.json` | sidecar state file |
| `DOWN_ALERT_TIMEOUT_MS` | `8000` | per-request timeout |

## Wire it up

Pick the scheduler for the box. **Critical:** run it *separately* from the engine — a watchdog
that lives inside the thing it watches dies with it.

### Linux / Mac — cron (every minute)

```cron
* * * * * DISCORD_WEBHOOK_URL="$DISCORD_WEBHOOK_URL" node /path/to/jarvis-trader/scripts/ops/down-alert.mjs >> /path/to/jarvis-trader/logs/down-alert.log 2>&1
```

### Windows — PM2 `cron_restart` (the deploy box already runs PM2)

Add a **second** app to [`engine/ecosystem.config.js`](../../engine/ecosystem.config.js). Because
the script is one-shot, run it as a periodic restart rather than a long-lived process:

```js
// alongside jarvis-engine / jarvis-dashboard / ib-gateway
{
  name: "down-alert",
  script: "scripts/ops/down-alert.mjs",
  interpreter: "node",
  autorestart: false,           // one-shot; cron_restart re-launches it
  cron_restart: "* * * * *",    // every minute
  env: { DISCORD_WEBHOOK_URL: process.env.DISCORD_WEBHOOK_URL },
}
```

`pm2 save` after adding it so it survives reboot (see [DASHBOARD_24_7.md](DASHBOARD_24_7.md)).

### Windows — Task Scheduler (alternative)

Trigger every 1-2 min → action `node C:\...\scripts\ops\down-alert.mjs`, with
`DISCORD_WEBHOOK_URL` set in the task's environment.

## Verify it works (30 seconds, no real outage needed)

```bash
# 1. Point it at a dead port → expect a DOWN alert on the 2nd run, then silence.
ENGINE_URL=http://localhost:59999 DOWN_ALERT_THRESHOLD=2 \
  DISCORD_WEBHOOK_URL="$DISCORD_WEBHOOK_URL" \
  node scripts/ops/down-alert.mjs; node scripts/ops/down-alert.mjs   # 2nd fires 🔴
# 2. Point it back at the real engine → expect one 🟢 RECOVERED, then silence.
ENGINE_URL=http://localhost:8010 DISCORD_WEBHOOK_URL="$DISCORD_WEBHOOK_URL" \
  node scripts/ops/down-alert.mjs
```

You should get exactly one 🔴 then one 🟢 in the channel — not a stream.

## Durability — "how many days straight has it run?"

Every time `down-alert.mjs` sees a recovery it appends the completed outage
(`downSince → recoveredAt`, duration) to an append-only ledger
(`DOWN_ALERT_EVENTS`, default `engine/data/down_alert_events.jsonl`).
[`scripts/ops/durability.mjs`](../../scripts/ops/durability.mjs) reads that ledger
plus the live state and reports the paper stack's clean-run durability — the
measurement half of the "clean uninterrupted paper run" goal:

```bash
node scripts/ops/durability.mjs          # human-readable
node scripts/ops/durability.mjs --json   # for a widget / endpoint
```

```
  🟢 CLEAN — 4.20 days straight (4.20d)
     monitoring since   2026-06-27T02:10:00.000Z
     outages recorded   1
     longest clean run  4.20d
     total downtime     3.4m
     MTBF               4.20d between failures
     last outage        …
```

It invents nothing: with no outages it says "no outage since monitoring began",
and with no data at all it says so and points back here. The headline **days
clean since the last outage** is the durability number — it only advances while
the stack actually stays up, so it can't be gamed by a restart. Run it whenever
you want the current streak, or wire the `--json` form into a dashboard widget.

## What it does NOT do

- It does **not** restart the engine (that's PM2 `autorestart` / `pm2-restart-monitor.ps1`).
- It does **not** judge data correctness or IB-feed health (that's `check-ib-data-watchdog.ps1`
  and `pnpm check:live` in [DASHBOARD_24_7.md](DASHBOARD_24_7.md)).
- It only answers one question, reliably, from outside: **is the engine up?** — and,
  via the ledger, **how long has it stayed up?**
