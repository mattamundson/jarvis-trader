#Requires -Version 5.1
<#
.SYNOPSIS
  Installs the JARVIS-TV-CDP-Watchdog scheduled task (runs every 10 minutes).

.NOTES
  launch-tv-with-cdp.ps1's own docstring documents this trigger --
  "JARVIS-TV-CDP-Watchdog (every 10min, -AutoHeal) --> covers auto-update /
  wake-from-sleep" -- but only the AtLogon trigger (install-tv-cdp-startup-task.ps1)
  was ever actually deployed. Found 2026-07-24: TradingView's chart renderer went
  unhealthy and the TV-sourced tick feed (tv_stream, plus AAPL/SPX reference
  panes) sat dead for 12+ hours with nothing to auto-recover it -- the engine's
  own retry loop (TVStreamer._run_loop) kept relaunching the Node CLI every
  ~5s-1h, but relaunching the CLI subprocess does not fix a broken TV Desktop
  chart layout; only recycling TV Desktop itself does, and launch-tv-with-cdp.ps1
  -AutoHeal is the only thing wired to do that. -AutoHeal only kills+relaunches
  TV Desktop inside the script's own safe window (weekday 18:00-07:00 CT or
  Sat/Sun) -- it is a no-op warning outside that window, so this task cannot
  interrupt Amo mid-session on a weekday afternoon.

  Run once. Re-run to update. Idempotent -- deletes and re-creates if already exists.
  Battery flags cleared (see rules/windows-pitfalls.md -- 0x800710E0 gate).
#>

$ErrorActionPreference = 'Stop'

$TaskName = 'JARVIS-TV-CDP-Watchdog'
$JarvisDir = 'C:\Users\mattm\ThinkorSwim\jarvis-trader'
$Script = "$JarvisDir\scripts\launch-tv-with-cdp.ps1"
$PwshExe = "$env:LOCALAPPDATA\Microsoft\WindowsApps\pwsh.exe"

if (-not (Test-Path $Script)) {
    Write-Host "ERROR: launch-tv-with-cdp.ps1 not found at $Script"
    exit 1
}

if (-not (Test-Path $PwshExe)) {
    $PwshExe = (Get-Command pwsh -ErrorAction Stop).Source
}

$action = New-ScheduledTaskAction -Execute $PwshExe `
    -Argument "-NonInteractive -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`" -AutoHeal" `
    -WorkingDirectory $JarvisDir

$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 10) `
    -Once -At (Get-Date)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable

# Remove existing task if present
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action   $action `
    -Trigger  $trigger `
    -Settings $settings `
    -RunLevel Limited `
    -Description "Every 10min: check TV Desktop CDP health, auto-heal (kill+relaunch) only inside the script's safe window (weekday 18:00-07:00 CT or weekends). Created 2026-07-24 to close the gap where the AtLogon-only trigger left a broken chart renderer with no ongoing recovery." `
    -Force | Out-Null

Write-Host "Installed: $TaskName (every 10 min, battery-gated cleared, -AutoHeal)"
Write-Host "Verify:    schtasks /Query /TN `"$TaskName`" /V /FO LIST"
Write-Host "Test now:  Start-ScheduledTask -TaskName `"$TaskName`""
Write-Host "Log:       Get-Content `"$env:USERPROFILE\jarvis-tv-cdp.log`" -Tail 20"
