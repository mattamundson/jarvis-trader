# TradingView MCP — Startup Persistence

**Status:** Active since 2026-04-21 (P0.1 of roadmap `ROADMAP_2026-Q2-Q4.md`)

## What this covers

TradingView Desktop must be launched with `--remote-debugging-port=9222` for the
`tradingview-mcp` server to connect via Chrome DevTools Protocol. Store-app
launches (from the Start menu, pinned taskbar icon, etc.) do NOT set this flag,
so CDP dies on every reboot unless we intervene.

This setup registers a scheduled task that launches TV with the flag at every
user logon.

## Files

| File | Purpose |
|---|---|
| `scripts/launch-tv-with-cdp.ps1` | The launcher. Idempotent — checks port 9222 before doing anything. |
| `scripts/install-tv-cdp-startup-task.ps1` | One-shot installer that registers the scheduled task. |
| `$env:USERPROFILE\jarvis-tv-cdp.log` | Run log (rotates at 1MB → `.log.1`). |

## Install

```powershell
pwsh -NoProfile -File scripts\install-tv-cdp-startup-task.ps1
```

No admin required. Registers task `JARVIS-TV-CDP-AtLogon` under the current user.

## Verify

```powershell
# Task is registered and ready
schtasks /Query /TN "JARVIS-TV-CDP-AtLogon" /FO LIST

# Trigger manually (simulates logon)
schtasks /Run /TN "JARVIS-TV-CDP-AtLogon"

# Check CDP is alive
Invoke-WebRequest http://localhost:9222/json/version -UseBasicParsing | Select -Expand Content

# Tail the run log
Get-Content "$env:USERPROFILE\jarvis-tv-cdp.log" -Tail 20

# End-to-end sanity check via the tv CLI
tv status
```

Expected `tv status` output:
```json
{
  "success": true,
  "cdp_connected": true,
  "chart_symbol": "CME_MINI:ES1!",
  ...
}
```

## Exit codes from the launcher

| Code | Meaning | Action |
|---|---|---|
| 0 | CDP alive (already was, or was just launched) | Nothing. |
| 1 | Hard failure (binary missing, launch didn't bind port) | Check log; likely a TV update changed the versioned path — see Troubleshooting. |
| 2 | Soft config gap: TV is running without CDP (user launched from Start menu) | Kill TV and re-run: `taskkill /IM TradingView.exe /F; schtasks /Run /TN "JARVIS-TV-CDP-AtLogon"`. |

## Troubleshooting

### "TV binary not found at ..."

TradingView Desktop is a Microsoft Store app. The install path contains the
version number: `C:\Program Files\WindowsApps\TradingView.Desktop_3.0.0.7652_x64__n534cwy3pjxzj\TradingView.exe`.
When the Store auto-updates TV, the `3.0.0.7652` segment changes and the binary
move invalidates our hardcoded path.

Fix: update `$tvBinary` in `launch-tv-with-cdp.ps1` to the new path. Find it via:
```powershell
Get-Process TradingView | Select-Object -First 1 -ExpandProperty Path
```

(A future iteration should resolve the path dynamically via AppsFolder URI —
tracked in roadmap as a sub-task of P0.1 hardening.)

### "TV running without CDP" (exit code 2)

The launcher refuses to kill a running TV session because it may have unsaved
chart layouts. If you're fine losing the session:

```powershell
Stop-Process -Name TradingView -Force
schtasks /Run /TN "JARVIS-TV-CDP-AtLogon"
```

### CDP port 9222 returns 404 on all endpoints

Rare Electron/Chromium bug. Force-kill and relaunch:

```powershell
Stop-Process -Name TradingView -Force
Start-Sleep 3
schtasks /Run /TN "JARVIS-TV-CDP-AtLogon"
```

### Task doesn't fire at logon

```powershell
# Check task history via Task Scheduler GUI (taskschd.msc) or:
Get-ScheduledTaskInfo -TaskName "JARVIS-TV-CDP-AtLogon"

# Confirm current user's logon triggers are enabled
Get-ScheduledTask -TaskName "JARVIS-TV-CDP-AtLogon" | Select -Expand Triggers
```

## Uninstall

```powershell
Unregister-ScheduledTask -TaskName "JARVIS-TV-CDP-AtLogon" -Confirm:$false
```

The launcher script is safe to leave in place for manual runs.

## Related

- Roadmap P0.1: `docs/ROADMAP_2026-Q2-Q4.md`
- TV MCP server: `tradingview-mcp/`
- TV MCP activation history: `docs/tradingview-kraken-integration-2026-04-16.md`
- Skill: `C:\Users\mattm\.claude\skills\jarvis-trader\SKILL.md`
