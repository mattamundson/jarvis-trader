# JARVIS Engine Crash Post-Mortem — 2026-09-10 03:26 CDT

Written by cron 5a6762293081 (control-plane recovery loop), tick 2026-09-10 ~05:45 CDT.
Scope: control-plane forensics only. No engine/risk config touched.

## Summary

pm2 `jarvis-engine` exited (exit_code=1, restarts 9→11) between **03:26:34 and 03:26:44 CDT**
on 2026-09-10. The process died **without a Python traceback and without any Windows crash
event**. PM2 + the engine's own port_guardian self-healed: new uvicorn server process 47384
started 03:28:13, all startup checks passed, health GREEN post-restart.

## Timeline (CDT, from engine/logs/engine-out.log + engine-error.log)

| Time | Event |
|---|---|
| 03:15–03:26 | Normal ops: margin monitor HEALTHY ($13,181.32, DD 0.0%), health 200s, IBKR :4002 connection-refused loop (550+ consecutive failures — gateway down, long-standing) |
| 03:26:13 | apscheduler: "SafetyLayer Equity Sync" missed by 3.8s (first sign of process stress) |
| 03:26:34 | **LAST LOG LINE** (old process): MarginMonitor HEALTHY |
| 03:26:44 | port_guardian (new boot): `port 8010 held by PID 41420 (unknown) — not a python/uvicorn process — REFUSING to kill` |
| 03:27:30 | port 8010 free; port_guardian launches uvicorn in-process |
| 03:28:13 | New server process 47384: startup checks ALL PASS (paper mode, kill switch restored from DB reason=daily_loss_limit, DO_NOT_TRADE sync OK {M2K,MNQ,MCL,MGC}, active symbols ['MES'] tradeable) |
| 03:28:16 | Signal handlers registered; engine serving |

## Evidence checked

1. `engine/logs/engine-error.log` — no Traceback, no CRITICAL (except the routine kill-switch
   restore notice), no exit marker; log simply stops at 03:26:34 and resumes with the new
   process banner at 03:27:36.
2. `engine/logs/engine-out.log` — port_guardian sequence above.
3. Windows Event Log (System + Application, 03:00–03:40): ZERO WER (1000/1001/1002),
   ZERO Application Error, ZERO Resource-Exhaustion-Detector events. Query verified against
   the log (6 unrelated Application events in window; none crash-related).
4. pm2: exit_code=1, created_at 2026-09-10T08:26:36Z, restarts 11.

## Root cause

**NOT DETERMINABLE from available evidence.** The signature (no Python traceback, no OS
crash event, exit_code=1) is most consistent with an **external/hard termination** of the
process — e.g., PM2 god-daemon action, an out-of-band `pm2 restart`, or a native-level
failure that bypassed both Python logging and WER. Memory exhaustion is NOT supported by
event-log evidence (no Resource-Exhaustion events today).

The apscheduler 3.8s miss 21 seconds before death is suggestive but not proof of process
stress; a 3.8s miss can also occur under transient load.

## Secondary findings (read-only observations)

1. **Logs were never actually frozen.** Tick-16's "pm2 log rotation broken" premise was
   based on `~/.pm2/logs/jarvis-engine-*.log` (mtime 2026-08-18). Those are STALE files from
   an old PM2 process config. The live log paths (per `pm2 describe jarvis-engine`) are
   `engine/logs/engine-{out,error}.log` — both FRESH (written within minutes at every check),
   and pm2-logrotate (online, daily rotateInterval) has produced dated rotated files
   (e.g. `engine-error__2026-09-10_00-00-00.log`). **Rotation is healthy; no fix needed.**
   The `~/.pm2/logs/jarvis-engine-*` + `.gz.gz.gz` chain is dead weight only.
2. **Persistent risk alert, pre-existing:** AlertManager has emitted
   `DRAWDOWN CRITICAL | Drawdown: -12.5% | Kill switch imminent` every ~30 min since at least
   00:00 while MarginMonitor reports DD 0.0% / equity $13,181.32 — indicates the safety-layer
   equity sync basis and margin-monitor basis disagree (or a stale equity snapshot feeds the
   alert). Kill switch is ALREADY active (restored from DB, reason=daily_loss_limit), so this
   is not an imminent action, but the -12.5% metric source should be reconciled by Amo or a
   [safety-review] PR before the alert is trusted or silenced. NOT touched by this loop.

## Verification state

- Engine /health 200 at 05:35 CDT: status ok, paper=true, kill_switch=true, live=false,
  llm_path_healthy=true, uptime ~7,616s (post-restart).
- This post-mortem is documentation-only; zero runtime changes made.
