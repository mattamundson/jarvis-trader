<#
.SYNOPSIS
  Schedules the LONG_GAP_FILL options paper-track loop (every 15 minutes,
  RTH-gated in-script) plus its dead-man heartbeat watcher. Idempotent.

.DESCRIPTION
  Registers:
    - jarvis-gapfill-papertrack            every 15 min from -StartTime, runs
                                           gapfill-papertrack-loop.ps1
    - jarvis-heartbeat-gapfill-papertrack  daily at -WatchTime, alerts if the
                                           loop stalled (heartbeat-check.ps1)

  LIVE-WRITING BY DEFAULT -- same documented, owner-approved deviation as
  register-options-signals-loop.ps1 (Amo, 2026-07-16): the house dry-run
  convention gates OUTWARD side effects, and this logger has none. It reads
  the paper_trades DB read-only, fetches public delayed CBOE quotes, and
  appends a local JSONL. A dry-run registration would record nothing, which
  defeats the whole point of paper-tracking. Pass -DryRun to override.

  15-minute cadence (vs 30 for options-signals): LONG_GAP_FILL trades are
  intraday with same-day exits; quotes are already 15-min delayed, so a
  15-min poll bounds worst-case exit-quote staleness at ~30 min. The trigger
  fires around the clock; weekday/RTH gating lives in
  gapfill_options_papertrack.py, which exits 0 on skipped fires.

  Both tasks register with battery flags cleared (INC-2: 0x800710E0).
  Re-running re-registers cleanly. Requires an elevated shell.

.EXAMPLE
  pwsh -File scripts\loops\register-gapfill-papertrack-loop.ps1
  pwsh -File scripts\loops\register-gapfill-papertrack-loop.ps1 -DryRun
#>

[CmdletBinding()]
param(
    [string] $RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string] $StartTime = "8:40am",
    [string] $WatchTime = "10am",
    [double] $MaxAgeHours = 2,
    [switch] $DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$pwshExe = (Get-Command pwsh -ErrorAction SilentlyContinue)?.Source
if (-not $pwshExe) { throw "pwsh.exe not found on PATH. Install PowerShell 7." }

$localTz = (Get-TimeZone).Id
if ($localTz -notmatch "Central") {
    Write-Warning "[register] machine timezone is '$localTz', not Central -- fires will be offset from CT, but the Python RTH gate keeps work inside 08:30-15:05 CT regardless."
}

$loopScript = Join-Path $RepoRoot "scripts\loops\gapfill-papertrack-loop.ps1"
$hbScript = Join-Path $RepoRoot "scripts\loops\heartbeat-check.ps1"
foreach ($s in @($loopScript, $hbScript)) {
    if (-not (Test-Path $s)) { throw "missing script: $s" }
}

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

function Register-Loop {
    param([string] $TaskName, [string] $Argument, [ciminstance] $Trigger)
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "[register] replaced existing task '$TaskName'"
    }
    $action = New-ScheduledTaskAction -Execute $pwshExe -Argument $Argument
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $Trigger `
        -Settings $settings -Description "jarvis-trader gapfill options paper-track loop" | Out-Null
}

$dryRunArg = if ($DryRun) { " -DryRun" } else { "" }
if ($DryRun) {
    Write-Host "[register] registering in DRY-RUN mode (compute + log, never writes)."
}
else {
    Write-Host "[register] registering LIVE-WRITING (owner-approved default for this read-only logger)."
}

$startAt = [datetime]::Parse((Get-Date).ToString("yyyy-MM-dd") + " " + $StartTime)
$repeatTrigger = New-ScheduledTaskTrigger -Once -At $startAt `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration ([TimeSpan]::FromDays(3650))

Register-Loop -TaskName "jarvis-gapfill-papertrack" `
    -Argument "-NoProfile -File `"$loopScript`"$dryRunArg" -Trigger $repeatTrigger
Write-Host "[register] 'jarvis-gapfill-papertrack' -> every 15 min from $StartTime (RTH-gated in-script)"

$watchTrigger = New-ScheduledTaskTrigger -Daily -At $WatchTime
Register-Loop -TaskName "jarvis-heartbeat-gapfill-papertrack" `
    -Argument "-NoProfile -File `"$hbScript`" -LoopName gapfill-papertrack -MaxAgeHours $MaxAgeHours" `
    -Trigger $watchTrigger
Write-Host "[register] 'jarvis-heartbeat-gapfill-papertrack' -> daily $WatchTime (max age ${MaxAgeHours}h)"

Write-Host "`nDone. Verify with:  Get-ScheduledTask -TaskName jarvis-*gapfill*"
Write-Host "Test now with:      Start-ScheduledTask -TaskName jarvis-gapfill-papertrack"
