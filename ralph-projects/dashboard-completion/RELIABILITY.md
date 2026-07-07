# JARVIS Trader — 24/7 Reliability (US-006 / US-007)

Verified 2026-06-12 against the live pm2 daemon.

## Current pm2 state (verified)

| Process | Status | Restarts | Notes |
|---|---|---|---|
| `jarvis-engine` | online | 4 | FastAPI engine :8010 |
| `jarvis-dashboard` | online | 0 | Next.js :3010 |
| `jarvis-bridge-api` | online | 0 | bridge :8020 |
| `master-api` | online | 0 | master-api |
| `jarvis-weekly-tearsheet` | **stopped** | 0 | **Expected** — weekly one-shot cron job, idle between runs. NOT a failure. |

All four long-running services are online with sane restart counts (engine 4 over the process lifetime). `pm2 save` has been run — `~/.pm2/dump.pm2` exists (saved 2026-06-11), so the process list is persisted.

## The one real gap: boot persistence

`pm2 startup` does **not** work on Windows ("Init system not found" — there is no systemd). So after a **reboot**, the pm2 daemon does not come back and the four services stay down until something runs `pm2 resurrect`. There is currently **no logon/boot task** doing that.

### Fix (AMO-GATED — Amo runs this once)

Register a logon scheduled task that resurrects the saved pm2 dump. Runs as the current user (LIMITED — no admin needed):

```powershell
# 1) make sure the current good state is saved
pm2 save

# 2) register a logon task that brings pm2 back after every login/reboot
$action  = New-ScheduledTaskAction -Execute "$env:LOCALAPPDATA\Microsoft\WindowsApps\pm2.cmd" -Argument "resurrect"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "Jarvis-PM2-Resurrect" -Action $action -Trigger $trigger -Settings $settings -Description "Resurrect pm2-managed JARVIS services at logon"
```

Notes:
- Uses the WindowsApps **shim** path for pm2.cmd (survives auto-updates) — see `rules/windows-pitfalls.md`.
- Battery flags included so the task isn't silently refused with `0x800710E0` (see windows-pitfalls battery-gate note).
- Verify after: `schtasks /Query /TN "Jarvis-PM2-Resurrect" /V /FO LIST` → Status: Ready, plausible Next Run.

Alternative (heavier): `pm2-installer` installs pm2 as a true Windows service. Not needed if the logon task is acceptable.

## One-command recovery (verified path)

- Engine only: `.\restart_engine.ps1` (PM2-aware; polls `/health`, ~229s steady-state). **Amo-run only.**
- Everything from saved state: `pm2 resurrect`
- Re-save after an intentional topology change: `pm2 save`

## Health verification (US-007)

After any restart, confirm per `rules/verification.md`:
- `Invoke-RestMethod http://127.0.0.1:8010/health` → `status=ok` AND `tradingview_mcp_healthy=true` AND `llm_path_healthy=true`
- `Invoke-RestMethod http://127.0.0.1:8010/brokers/positions` → authoritative IB state (health's data_ib/exec_ib can be cosmetically null even when IB is connected)

### Watchdog verification (live, 2026-06-12)

Confirmed present + recently fired (LastTaskResult 0 = success):

| Task | State | Last run | Result |
|---|---|---|---|
| `Jarvis-LLMWatchdog` | Ready | 09:15 today | 0 ✅ |
| `Jarvis-SystemStatus` | Ready | 08:45 today | 0 ✅ |
| `Jarvis-HealthWatchdog` | Ready | 16:00 today | 0 ✅ |
| `Jarvis-EngineWatchdog` | Ready | 16:45 today | 0 ✅ |
| `Jarvis-Sentinel` / `-Dashboard` | Running | — | 267009 (=running, normal) |
| `Jarvis-Sentinel-DeadMan` | Ready | 16:43 today | 0 ✅ |
| `JARVIS-BrainDaemon-Watchdog` | Ready | 16:41 today | 0 ✅ |
| `Jarvis-OllamaRouter-Watchdog` | Ready | 16:45 today | 0 ✅ |
| **`Jarvis-DataIntegritySentinel`** | Ready | 05:35 today | **1 ❌ FAILING** |

### 🔴 Surfaced for Amo

1. **`Jarvis-DataIntegritySentinel` is failing** (LastTaskResult=1, daily ~05:35). A monitor that itself errors is silently blind — investigate its script/exit contract.
2. **IB Gateway is dark right now.** `/health` reports `data_ib=None, exec_ib=None` and `/brokers/positions` returns a detail-error (0 positions, connected=None). This is the known PR #34 IB data-leg clientId-collision condition; the fix is merged-pending and needs an **Amo-run engine restart** (`.\restart_engine.ps1`) to apply. The dashboard /health page renders this honestly (IB shows Disconnected/error, not a false green) — verified at `app/health/page.tsx:166-171,225`.
3. `JARVIS-TV-CDP-Watchdog` is **Disabled** (last run 2026-05-19) — confirm intentional (TV Desktop not installed) vs. accidental.
