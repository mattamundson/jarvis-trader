# install-tv-cdp-startup-task.ps1 — Register Windows Task Scheduler task
# "JARVIS-TV-CDP-AtLogon" to run launch-tv-with-cdp.ps1 at user login.
#
# Ensures the TradingView MCP server has a live CDP endpoint to connect to
# whenever the user logs in. Removes the manual setup burden after every reboot.
#
# Idempotent: deletes any prior registration with the same task name before
# re-creating. Safe to re-run after changes to the script or schedule.
#
# No admin required — runs under the current interactive user account.
#
# Usage:
#   pwsh -NoProfile -File scripts\install-tv-cdp-startup-task.ps1
#
# Verify after registration:
#   schtasks /Query /TN "JARVIS-TV-CDP-AtLogon" /FO LIST
#   schtasks /Run /TN "JARVIS-TV-CDP-AtLogon"   # trigger immediately
#
# Uninstall:
#   Unregister-ScheduledTask -TaskName "JARVIS-TV-CDP-AtLogon" -Confirm:$false

$ErrorActionPreference = "Stop"

$taskName = "JARVIS-TV-CDP-AtLogon"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$psScript = Join-Path $repoRoot "scripts\launch-tv-with-cdp.ps1"
# Prefer the per-user WindowsApps shim — a reparse point that redirects to the
# currently-installed pwsh, so the scheduled task's Command field survives Store
# auto-updates (e.g. PowerShell 7.6.0 → 7.6.1). Without this, `Get-Command pwsh`
# returns a version-stamped WindowsApps path that rots on every pwsh update,
# causing the task to fail silently at login with ERROR_FILE_NOT_FOUND.
$shimPwsh = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\pwsh.exe"
if (Test-Path $shimPwsh) {
    $pwsh = $shimPwsh
} else {
    $pwsh = (Get-Command pwsh -ErrorAction SilentlyContinue)?.Source
    if (-not $pwsh) { $pwsh = "pwsh" }
}

# ── Pre-flight ─────────────────────────────────────────────────────────────────
if (-not (Test-Path $psScript)) {
    Write-Host "ERROR: launch-tv-with-cdp.ps1 not found at $psScript"
    exit 1
}

Write-Host "Registering task: $taskName"
Write-Host "  Script : $psScript"
Write-Host "  Trigger: at every user logon (+ 30s delay to let Windows settle)"
Write-Host ""

# ── Remove prior registration ─────────────────────────────────────────────────
try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
} catch {}

# ── Build task components ──────────────────────────────────────────────────────
$action = New-ScheduledTaskAction `
    -Execute $pwsh `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$psScript`"" `
    -WorkingDirectory $repoRoot

# AtLogon for current user, 30s delay so the desktop shell is fully loaded
$trigger = New-ScheduledTaskTrigger -AtLogon -User $env:USERNAME
$trigger.Delay = "PT30S"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

# ── Register ──────────────────────────────────────────────────────────────────
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Launch TradingView Desktop with Chrome DevTools Protocol enabled so the tradingview-mcp server has a live CDP endpoint. Created by JARVIS TRADER roadmap P0.1." | Out-Null

Write-Host "Registered successfully."
Write-Host ""
Write-Host "To trigger immediately (for testing):"
Write-Host "  schtasks /Run /TN `"$taskName`""
Write-Host ""
Write-Host "To view the run log:"
Write-Host "  Get-Content `"$env:USERPROFILE\jarvis-tv-cdp.log`" -Tail 20"
