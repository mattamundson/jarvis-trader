# JARVIS health probe and dead-man checklist

Source-mining wave: GitHub repo consolidation wave 6.

Sources mined:
- `mattamundson/jarvis-sentinel` (`main`, pushed 2026-06-06): Sentinel MVP README, `sentinel.example.yaml`, `sentinel/probes/*`, `scripts/deadman-switch.ps1`, `scripts/install-deadman-task.ps1`, design spec, and MVP plan.
- Current `jarvis-trader` surfaces: `engine/routers/health_router.py`, `engine/scripts/health_watchdog.py`, `engine/scripts/liveness_watchdog.py`, `scripts/engine-watchdog.ps1`, `scripts/install-engine-watchdog-task.ps1`, `watchdog_engine.ps1`, and existing health tests.

This runbook is docs-only. It does not change PM2, Windows Scheduled Tasks, live trading config, risk limits, kill-switch behavior, broker routing, `.env`, API keys, active instrument gates, or order behavior.

## Objective

Make health monitoring falsifiable: every page-worthy failure must map to a named probe, a source of truth, debounce rules, delivery verification, and a safe operator action.

The target structure is a three-layer watchdog stack:

1. In-process truth: engine `/health*` endpoints summarize JARVIS subsystem state.
2. Host-local watcher: a Windows/Python watchdog polls the engine and alerts on sustained transitions.
3. Dead-man watcher: an independent task watches the watcher heartbeat and pages if the watcher stops.

## Probe inventory

| Layer | Current JARVIS surface | Sentinel pattern to preserve | Healthy condition | Page-worthy condition | Safe action |
|---|---|---|---|---|---|
| Engine liveness | `GET /health`; `GET /health/watchdog`; `engine/scripts/health_watchdog.py`; `engine/scripts/liveness_watchdog.py` | `EngineProbe` polls `http://127.0.0.1:8010/health` with timeout + restart grace | HTTP 200 and `status == ok` or explicitly understood degraded state | Endpoint unreachable for sustained debounce window, or `status != ok` persists | Read logs, confirm port owner, use documented restart procedure only when already authorized |
| Supervision parity | `GET /health/supervision`; `GET /health/pm2` | Topology-aware root-cause instead of leaf alert storm | PM2 state agrees with TCP port owner for `jarvis-engine`, `jarvis-dashboard`, and bridge API | PM2 says online while port is closed, or port is live under an orphan PID | Diagnose PM2 vs orphan process; avoid blind force-kill unless runbook explicitly says so |
| IB Gateway liveness | `/health` fields: `ibgateway_alive`, `ibgateway_port`, `ibkr_*_connected`; `GET /ib/connection-test` | Probe dependency separately from engine process | Gateway accepts TCP on configured paper port and connector status is not stale | Gateway down or connector disconnected/stale during a trading window | Treat as data/execution-path incident; do not route live orders; escalate for manual gateway recovery |
| Kill switch visibility | `/health.kill_switch_active`; `/health/full.safety_layer` | Safety rules are observed, not reimplemented by Sentinel | Kill-switch state is explicit and visible | Kill switch becomes active or health hides the active state | Stop at diagnosis; changing kill-switch logic or thresholds requires `[safety-review]` PR |
| LLM path | `/health.llm_path_healthy`; `GET /health/llm` | Synthetic canary + provider exhaustion probe | Provider chain has an available primary/fallback and recent call metrics are below warning bands | Exhausted provider chain, repeated fallback, p95 latency/cost breach, or canary failure | Degrade research/briefing jobs; do not fake decisions; provider/config changes are separate ops work |
| Market data freshness | `/health` market-data and freshness fields; `GET /system/data-integrity` | Probe source freshness, not only process uptime | Data timestamps are within accepted freshness bands for the session | Freshness stale while process is up | Block confidence claims; trigger data-feed triage; do not bypass gates |
| TradingView / chart capture | `/health.tradingview_mcp_healthy`; `/health.tradingview_mcp_details`; TV CDP watchdog tests | Grace cache distinguishes transient CDP flap from steady not-running state | CDP probe green or not-running explicitly understood as expected | Flapping after grace window or required chart-capture path unavailable | Mark discretionary chart review degraded; do not infer trade signals from missing captures |
| Alert delivery | Notifier-backed watchdog delivery paths; Discord/Telegram integrations | `DeliveryProbe` checks Discord/Twilio credentials without sending live pages | At least one independent out-of-band alert channel is deliverable | Webhook/token dead, channel revoked, or no configured delivery path | Repair credentials out-of-band; do not claim monitoring coverage until a self-test/readback verifies it |
| Watchdog heartbeat | Add/standardize heartbeat file emitted by local watcher | `runtime/heartbeat.txt` + `deadman-switch.ps1` every 5 minutes | Heartbeat mtime under threshold | Heartbeat missing or stale beyond threshold | Page "watcher down"; restart watcher only through scheduled-task runbook |

## Debounce and grace rules

Use explicit debounce so the system does not restart during normal load spikes.

- Engine HTTP probe: require consecutive misses, not a single failed poll.
  - Current `engine/scripts/liveness_watchdog.py` defaults: 60-second interval, 3 misses before DOWN alert.
  - Current `scripts/engine-watchdog.ps1`: 3 probes, 15-second timeout, 8-second gaps before restart consideration.
- Restart grace: preserve the `jarvis-sentinel` `EngineProbe` pattern where a known restart window returns a truthful OK/silent status until startup grace expires.
- Event-loop saturation guard: preserve the current log-recency check before any disruptive restart. A fresh engine log means a slow `/health` can be saturation, not death.
- Cross-watchdog lock: preserve the temp restart lock before any kill/restart path. Competing watchdogs must skip instead of colliding into a restart storm.
- Recovery edge: page once on DOWN transition and once on RECOVERY. Do not page every poll.

Recommended default thresholds for a future consolidation PR:

| Signal | Default | Why |
|---|---:|---|
| Health poll interval | 60 seconds | Fast enough for trading-hours awareness without dashboard-style load |
| Miss threshold | 3 consecutive misses | Filters transient 1-2 tick stalls |
| HTTP timeout | 8-15 seconds | Matches current liveness and PowerShell watchdog tolerances |
| Dead-man task interval | 5 minutes | Matches `jarvis-sentinel` task and current watchdog cadence |
| Dead-man stale threshold | 2 task periods + 1 grace period | Avoids false page from a delayed task launch |
| PM2 restart-rate warning | 4 restarts / 60 minutes | Matches current `health_watchdog.py` instability detector |

## Dead-man contract

A watcher is not real until something watches it.

Minimum heartbeat contract:

```json
{
  "component": "jarvis-health-watchdog",
  "ts_utc": "2026-09-12T00:00:00Z",
  "engine_url": "http://127.0.0.1:8010",
  "last_probe_status": "ok|degraded|down|skipped",
  "consecutive_misses": 0,
  "delivery_channels_configured": ["discord", "telegram"],
  "version": 1
}
```

Rules:

1. Write the heartbeat on every watcher tick, including skipped/out-of-session ticks.
2. The dead-man task reads file mtime first; JSON parse is a secondary diagnostic.
3. A stale heartbeat pages independently of engine health. The failure is "monitoring blind", not "engine down".
4. The dead-man task must use credentials available to scheduled tasks. `jarvis-sentinel/scripts/deadman-switch.ps1` correctly checks the User environment for `SENTINEL_DISCORD_WEBHOOK` before falling back to process env.
5. External/cloud heartbeat pings are optional but valuable. If added, keep them out-of-band and never depend on the JARVIS engine or Hermes provider chain.

## Delivery verification checklist

Before declaring the monitoring stack covered:

- [ ] Identify every alert channel used by the watchdog: Discord, Telegram, Twilio/SMS, desktop toast.
- [ ] Verify credential presence without printing secrets.
- [ ] Run a self-test that sends a labeled non-trading alert.
- [ ] Read back delivery evidence where the provider supports it, or capture the notifier success result and log row.
- [ ] Confirm at least one delivery path survives engine failure. Engine-internal notifier success alone is not enough for a dead engine.
- [ ] Confirm scheduled-task environment can see the same credential source as the interactive shell.
- [ ] Record the evidence path in the session handoff or runbook update.

Do not claim a channel is operational from static config only.

## Trading safety guardrails

- Health monitors may observe `LIVE_TRADING_ENABLED`, paper mode, active instruments, validation-only state, and kill-switch state.
- Health monitors must not override `DO_NOT_TRADE_SYMBOLS`, order approval gates, broker routing, or kill-switch thresholds.
- Any code change that alters restart behavior, paper/live selection, risk limits, `engine/config.py`, `engine/risk/`, `paper_config.py`, active instrument gates, or kill-switch behavior requires a dedicated `[safety-review]` PR.
- A monitoring alert can recommend a human action; it must not silently place, modify, or cancel trades.
- Stale or unavailable market data should degrade confidence and block claims, not trigger gate bypass.

## Operator triage flow

1. Check `/health/watchdog` first for minimal liveness. It is intentionally cheap and unauthenticated.
2. Check `/health` for the top-line process, database, safety, broker, LLM, and freshness fields.
3. Check `/health/assertions` for named pass/fail assertions that can be pasted into an incident note.
4. Check `/health/supervision` to compare PM2 belief against actual port liveness.
5. If `/health` is unreachable, check the watchdog heartbeat and PM2/port owner before restart.
6. If delivery failed, treat monitoring as degraded even if the engine is green.
7. If kill-switch or risk state is involved, stop at observation unless a `[safety-review]` PR exists.
8. After recovery, log: trigger, first failing probe, debounce count, action taken, recovery timestamp, and evidence links.

## Future implementation slices

These are intentionally small and separable:

1. Heartbeat sidecar: add a JSON heartbeat write to `engine/scripts/health_watchdog.py` or consolidate on `engine/scripts/liveness_watchdog.py`.
2. Dead-man task: port the `jarvis-sentinel` dead-man pattern into `jarvis-trader/scripts/` with `--dry-run` and no default destructive action.
3. Delivery probe: add a non-sending credential/webhook verifier to the watchdog self-test path.
4. Dashboard card: surface heartbeat age, last alert delivery status, and PM2/port mismatch in Mission Control.
5. External heartbeat: optional out-of-band ping target for whole-machine darkness detection.

Slice 1 can be a normal PR if it only writes a local heartbeat artifact. Slices 2-5 need explicit review of scheduled-task behavior and alert delivery. Any slice that changes restart/kill behavior is `[safety-review]`.

## Acceptance criteria for the next PR

- Docs/spec PR: this checklist exists, source repos are cited, and no runtime files change.
- Heartbeat PR: one-shot watcher run writes valid heartbeat JSON; stale heartbeat test fails deterministically.
- Dead-man PR: dry-run proves stale/missing heartbeat classification without sending live alerts by default.
- Delivery PR: self-test proves at least one out-of-band channel without exposing tokens.
- Dashboard PR: component renders stale/fresh states from fixed fixtures and does not poll heavy endpoints more often than the documented cadence.
