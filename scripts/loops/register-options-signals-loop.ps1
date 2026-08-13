<#
.SYNOPSIS
  Schedules the SPY/QQQ options-implied snapshot loop (every 30 minutes,
  RTH-gated in-script) plus its dead-man heartbeat watcher. Idempotent.

.DESCRIPTION
  Registers:
    - jarvis-options-signals            every 30 min from -StartTime, runs
                                        options-signals-loop.ps1
    - jarvis-heartbeat-options-signals  daily at -WatchTime, alerts if the loop
                                        stalled (reuses heartbeat-check.ps1)

  LIVE-WRITING BY DEFAULT -- a documented, owner-approved deviation from the
  house dry-run-default convention (Amo, 2026-07-16): that convention gates
  OUTWARD side effects (Discord posts, orders), and this generator has none --
  its only side effect is a local JSON that the owner's own dashboard reads
  with LIVE/STALE provenance badges. Registering dry-run would just make the
  dashboard section empty until a second manual step, gating nothing. Pass
  -DryRun to override if you want the strict convention anyway.

  The trigger fires every 30 minutes around the clock; weekday/RTH gating
  lives in options_signals_snapshot.py (08:30-15:05 CT), which exits 0 on
  skipped fires so heartbeats stay green on weekends. Both tasks register
  with battery flags cleared (INC-2: 0x800710E0 silent refusals on battery).

  Re-running re-registers cleanly. Requires an elevated shell.

.PARAMETER StartTime
  Local wall-clock anchor for the 30-min repetition (default 8:35am).

  CAVEAT: Task Scheduler fires in the MACHINE's local timezone; the Python
  RTH gate is CT-correct regardless, so a timezone mismatch only shifts when
  the skipped fires happen -- it can never produce off-hours snapshots.

.EXAMPLE
  pwsh -File scripts\loops\register-options-signals-loop.ps1
  pwsh -File scripts\loops\register-options-signals-loop.ps1 -DryRun
#>

[CmdletBinding()]
param(
    [string] $RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string] $StartTime = "8:35am",
    [string] $WatchTime = "10am",
    [double] $MaxAgeHours = 2,        # >= 3 fires while awake; wake catch-up re-greens fast
    [switch] $DryRun                   # strict-convention override; default is live-writing
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$pwshExe = (Get-Command pwsh -ErrorAction SilentlyContinue)?.Source
if (-not $pwshExe) { throw "pwsh.exe not found on PATH. Install PowerShell 7." }

$localTz = (Get-TimeZone).Id
if ($localTz -notmatch "Central") {
    Write-Warning "[register] machine timezone is '$localTz', not Central -- the 30-min fires will be offset from CT, but the Python RTH gate keeps snapshots inside 08:30-15:05 CT regardless."
}

$loopScript = Join-Path $RepoRoot "scripts\loops\options-signals-loop.ps1"
$hbScript = Join-Path $RepoRoot "scripts\loops\heartbeat-check.ps1"
foreach ($s in @($loopScript, $hbScript)) {
    if (-not (Test-Path $s)) { throw "missing script: $s" }
}

# Battery flags per INC-2 (rules/windows-pitfalls.md): without them every fire
# on battery is refused with 0x800710E0.
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
        -Settings $settings -Description "jarvis-trader options-signals loop" | Out-Null
}

$dryRunArg = if ($DryRun) { " -DryRun" } else { "" }
if ($DryRun) {
    Write-Host "[register] registering in DRY-RUN mode (fetch + compute + log, never writes)."
}
else {
    Write-Host "[register] registering LIVE-WRITING (owner-approved default for this read-only loop)."
}

$startAt = [datetime]::Parse((Get-Date).ToString("yyyy-MM-dd") + " " + $StartTime)
$repeatTrigger = New-ScheduledTaskTrigger -Once -At $startAt `
    -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration ([TimeSpan]::FromDays(3650))

Register-Loop -TaskName "jarvis-options-signals" `
    -Argument "-NoProfile -File `"$loopScript`"$dryRunArg" -Trigger $repeatTrigger
Write-Host "[register] 'jarvis-options-signals' -> every 30 min from $StartTime (RTH-gated in-script)"

$watchTrigger = New-ScheduledTaskTrigger -Daily -At $WatchTime
Register-Loop -TaskName "jarvis-heartbeat-options-signals" `
    -Argument "-NoProfile -File `"$hbScript`" -LoopName options-signals -MaxAgeHours $MaxAgeHours" `
    -Trigger $watchTrigger
Write-Host "[register] 'jarvis-heartbeat-options-signals' -> daily $WatchTime (max age ${MaxAgeHours}h)"

Write-Host "`nDone. Verify with:  Get-ScheduledTask -TaskName jarvis-*options-signals*"
Write-Host "Test now with:      Start-ScheduledTask -TaskName jarvis-options-signals"
