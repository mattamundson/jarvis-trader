<#
.SYNOPSIS
  Schedules the automated morning framing brief (ES/NQ AMT read) plus its
  dead-man heartbeat watcher on Windows. Idempotent.

.DESCRIPTION
  Registers:
    - jarvis-morning-framing-brief    weekday-only at -BriefTime, runs
                                       morning-framing-brief-loop.ps1
    - jarvis-heartbeat-framing-brief  daily at -WatchTime, alerts if the brief
                                       stalled (reuses the existing generic
                                       heartbeat-check.ps1 watcher)

  SAFETY DEFAULT: registers in -DryRun mode (generates + saves, never posts to
  Discord) until you explicitly pass -Live. This is the rollout-gating period
  called for in the framing-brief plan — run dry-run for several trading days,
  compare the saved briefs in engine/data/framing_briefs/ against Corey's
  actual same-morning post, and only re-run this script with -Live once you
  trust the output.

  Re-running re-registers cleanly (unregisters same-named tasks first).
  Requires an elevated shell to register scheduled tasks.

.PARAMETER BriefTime
  Local wall-clock time the brief runs, weekdays only (default 8:15am).

  CAVEAT: Windows Task Scheduler's -At fires in the MACHINE's local timezone.
  SKILL.md's framing-brief workflow assumes the trader's clock is CT
  (America/Chicago). If this machine's local timezone is not already CT,
  8:15am here will NOT mean 8:15am CT — check `Get-TimeZone` before trusting
  this trigger, the same clock-mismatch failure mode SKILL.md's own Step 0
  was written to prevent.

.EXAMPLE
  pwsh -File scripts\loops\register-framing-brief-loop.ps1
  pwsh -File scripts\loops\register-framing-brief-loop.ps1 -BriefTime 8:15am -Live
#>

[CmdletBinding()]
param(
    [string] $RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string] $BriefTime = "8:15am",
    [string] $WatchTime = "10am",
    [double] $MaxAgeHours = 30,      # weekday loop + weekend/holiday grace
    [switch] $Live                    # omit for the recommended dry-run default
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$pwshExe = (Get-Command pwsh -ErrorAction SilentlyContinue)?.Source
if (-not $pwshExe) { throw "pwsh.exe not found on PATH. Install PowerShell 7." }

$localTz = (Get-TimeZone).Id
if ($localTz -notmatch "Central") {
    Write-Warning "[register] machine timezone is '$localTz', not Central. -BriefTime $BriefTime will NOT align with SKILL.md's CT clock assumption -- verify before trusting this schedule."
}

$briefScript = Join-Path $RepoRoot "scripts\loops\morning-framing-brief-loop.ps1"
$hbScript = Join-Path $RepoRoot "scripts\loops\heartbeat-check.ps1"
foreach ($s in @($briefScript, $hbScript)) {
    if (-not (Test-Path $s)) { throw "missing script: $s" }
}

function Register-WeekdayLoop {
    param([string] $TaskName, [string] $Argument, [string] $At)
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "[register] replaced existing task '$TaskName'"
    }
    $action = New-ScheduledTaskAction -Execute $pwshExe -Argument $Argument
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $At
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Description "jarvis-trader loop (weekday-only)" | Out-Null
    Write-Host "[register] '$TaskName' -> weekdays $At"
}

$dryRunArg = if ($Live) { "" } else { " -DryRun" }
if (-not $Live) {
    Write-Host "[register] registering in DRY-RUN mode (generates + saves, never posts). Re-run with -Live once validated."
}

Register-WeekdayLoop -TaskName "jarvis-morning-framing-brief" `
    -Argument "-NoProfile -File `"$briefScript`"$dryRunArg" -At $BriefTime

Register-WeekdayLoop -TaskName "jarvis-heartbeat-framing-brief" `
    -Argument "-NoProfile -File `"$hbScript`" -LoopName morning-framing-brief -MaxAgeHours $MaxAgeHours" `
    -At $WatchTime

Write-Host "`nDone. Verify with:  Get-ScheduledTask -TaskName jarvis-*framing-brief*"
Write-Host "Test now with:      Start-ScheduledTask -TaskName jarvis-morning-framing-brief"
