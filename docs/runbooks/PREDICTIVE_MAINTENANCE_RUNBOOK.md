# Predictive Maintenance Runbook

## What it does

The predictive maintenance monitor watches four engine health signals and
assigns a degradation score from 0.0 (healthy) to 1.0 (imminent failure).
When the score exceeds the threshold (default 0.7) it logs a WARNING and
optionally POSTs a webhook alert (Discord / Telegram).

In alert-only mode (the default) it never restarts the engine on its own.
Auto-restart must be explicitly unlocked via a second flag.

---

## Degradation score — four inputs

| Signal | Weight | Condition |
|---|---|---|
| Memory growth rate | 0.30 | Process RSS growing > 200 MB/hour (rolling 2h window) |
| IB reconnect spike | 0.30 | More than 5 `[IB] reconnect` events in the log in the last 1 hour |
| LLM latency creep | 0.20 | p95 LLM call latency exceeds 2× the configured baseline (default 5 000 ms) |
| PM2 restart delta | 0.20 | `pm2 jlist` restart count for `jarvis-engine` increased in the last 10 minutes (crash already started) |

All four are independent; missing data (e.g., pm2 not installed, no LLM calls
yet) contributes 0.0 rather than erroring.

Score formula: each signal contributes 0 or its weight (partial credit only on
memory growth, proportional to rate / threshold). Weighted sum is capped at 1.0.

---

## Enable in stages (recommended rollout)

### Stage 1 — Alert only (run for at least one week)

Add to `engine/.env`:

```
ENABLE_PREDICTIVE_MAINTENANCE=1
PREDICTIVE_MAINTENANCE_ALLOW_RESTART=0
PREDICTIVE_MAINTENANCE_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

Restart the engine (`.\restart_engine.ps1`). The monitor starts alongside
the engine and samples every 5 minutes (interval is not configurable at
runtime — edit `monitor_loop(interval_seconds=300)` in
`engine/monitoring/predictive_maintenance.py` if needed).

Watch `engine/logs/health_samples.jsonl` and the WARNING logs for score
spikes. Tune thresholds via env vars if the signal is too noisy:

| Env var | Default | Description |
|---|---|---|
| `PM_MEM_GROWTH_MB_PER_HOUR` | 200 | Memory growth threshold |
| `PM_IB_RECONNECT_THRESHOLD` | 5 | IB reconnect count in 1h |
| `PM_LLM_LATENCY_BASELINE_MS` | 5000 | LLM p95 baseline |
| `PM_SCORE_THRESHOLD` | 0.7 | Score above which WARNING fires |
| `PM_RESTART_COOLDOWN_SECONDS` | 3600 | Minimum gap between restarts |

### Stage 2 — Enable preemptive restart

Once you have observed at least one week of alert-only data and the alerts are
actionable (i.e., the engine was indeed degrading when the score spiked), add:

```
PREDICTIVE_MAINTENANCE_ALLOW_RESTART=1
```

Restart the engine. The monitor will now call `pm2 restart jarvis-engine`
when the score exceeds the threshold, subject to the 1-hour cooldown.

---

## How to disable

Set both flags to 0 and restart the engine:

```
ENABLE_PREDICTIVE_MAINTENANCE=0
PREDICTIVE_MAINTENANCE_ALLOW_RESTART=0
```

The `asyncio.create_task(monitor.monitor_loop())` line in `main.py` checks
the flag at boot — the task is never created when the flag is 0.
If you disable the flag without restarting, the already-running loop will
sleep between iterations and re-check the flag each time; it stops acting
on findings but does not exit. A full restart is the clean path.

---

## Restart cooldown (anti-flap)

Only one preemptive restart per hour (`PM_RESTART_COOLDOWN_SECONDS`).
If the degradation signal does not clear after a restart, the monitor will
log WARNINGs on subsequent samples but will not fire a second restart until
the cooldown elapses. This prevents cascading restarts if the root cause
is not the memory leak (e.g., network outage causing IB reconnect spikes).

---

## Restart authority

The only pm2 command issued is:

```
pm2 restart jarvis-engine
```

This is identical to what `restart_engine.ps1` invokes in its PM2 path.
The monitor never bypasses pm2, never uses `taskkill`, and never modifies
the `.env` file (the IBKR_CLIENT_ID rotation that `restart_engine.ps1` does
is skipped — preemptive restarts reuse the existing client ID).

---

## Mid-flight trade risk

**Key concern:** if the engine restarts while a paper trade is open, the
in-memory approval queue and open-position state must be rebuilt from SQLite.
The existing `paper_tracker.reload_open_positions_from_db()` call in the
lifespan startup handles this — positions are not lost.

However, orders in the approval queue that have not been persisted to SQLite
yet (within the 1-minute approval-expiry window) may be silently dropped.
The autonomous scheduler's 5-minute TTL for pending approvals means that, in
practice, any trade that has been queued for more than 5 minutes and not yet
acted on will already have expired before a preemptive restart fires.

For live trading (Phase 3, currently disabled), review this assumption before
enabling `PREDICTIVE_MAINTENANCE_ALLOW_RESTART=1`.

---

## Observability

- **Score log:** `engine/logs/health_samples.jsonl` — one JSON line per sample
- **Score endpoint:** `GET /health/predictive` (requires API key)
  - Returns `{"enabled": false}` with HTTP 501 when flag is off
  - Returns latest sample + score + last-hour history when enabled
- **WARNING logs:** appear in `engine/logs/jarvis.log` and pm2 log stream

---

## Cross-references

- `[[STARK_MODE_OPERATING_PHILOSOPHY]]` — Stark mode is orthogonal to this monitor;
  predictive maintenance watches system health, not signal quality or regime gating.
- `[[AUTONOMOUS_PIPELINE_RUNBOOK]]` — the autonomous pipeline scheduler uses a separate
  tick-based approach (ENABLE_AUTONOMOUS_PIPELINE); they do not interact.
- `engine/monitoring/predictive_maintenance.py` — source of truth for score computation
- `engine/tests/test_predictive_maintenance.py` — 14 unit tests covering all paths
