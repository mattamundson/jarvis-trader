<#
.SYNOPSIS
  Schedules the automated pre-close framing brief (ES/NQ Acceptance-vs-Rejection
  read) plus its dead-man heartbeat watcher on Windows. Idempotent.

.DESCRIPTION
  Registers:
    - jarvis-preclose-framing-brief    weekday-only at -BriefTime, runs
                                        preclose-framing-brief-loop.ps1
    - jarvis-heartbeat-preclose-framing-brief  daily at -WatchTime, alerts if
                                        the brief stalled (reuses the existing
                                        generic heartbeat-check.ps1 watcher)

  Sibling to register-framing-brief-loop.ps1 (the premarket registration
  script) — same structure, own task names, own heartbeat task, so a preclose
  failure can never be masked by a premarket success.

  SAFETY DEFAULT: registers in -DryRun mode (generates + saves, never posts to
  Discord) until you explicitly pass -Live. Run dry-run for several trading
  days, compare the saved briefs in engine/data/framing_briefs/ (the
  `{date}-preclose.md` files) against Corey's actual same-afternoon pre-close
  post, and only re-run this script with -Live once you trust the output.

  Re-running re-registers cleanly (unregisters same-named tasks first).
  Requires an elevated shell to register scheduled tasks.

.PARAMETER BriefTime
  Local wall-clock time the brief runs, weekdays only (default 1:55pm) — ahead
  of Corey's own observed ~2:00-2:40pm CT pre-close posting window, mirroring
  the premarket task firing ahead of Corey's ~8:30-8:55am posts.

  CAVEAT: Windows Task Scheduler's -At fires in the MACHINE's local timezone.
  market-close-brief/SKILL.md's workflow assumes the trader's clock is CT
  (America/Chicago). If this machine's local timezone is not already CT,
  1:55pm here will NOT mean 1:55pm CT — check `Get-TimeZone` before trusting
  this trigger, the same clock-mismatch failure mode the premarket skill's own
  Step 0 was written to prevent.

.EXAMPLE
  pwsh -File scripts\loops\register-preclose-framing-brief-loop.ps1
  pwsh -File scripts\loops\register-preclose-framing-brief-loop.ps1 -BriefTime 1:55pm -Live
#>

[CmdletBinding()]
param(
    [string] $RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string] $BriefTime = "1:55pm",
    [string] $WatchTime = "4pm",
    [double] $MaxAgeHours = 30,      # weekday loop + weekend/holiday grace
    [switch] $Live                    # omit for the recommended dry-run default
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$pwshExe = (Get-Command pwsh -ErrorAction SilentlyContinue)?.Source
if (-not $pwshExe) { throw "pwsh.exe not found on PATH. Install PowerShell 7." }

$localTz = (Get-TimeZone).Id
if ($localTz -notmatch "Central") {
    Write-Warning "[register] machine timezone is '$localTz', not Central. -BriefTime $BriefTime will NOT align with market-close-brief/SKILL.md's CT clock assumption -- verify before trusting this schedule."
}

$briefScript = Join-Path $RepoRoot "scripts\loops\preclose-framing-brief-loop.ps1"
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

Register-WeekdayLoop -TaskName "jarvis-preclose-framing-brief" `
    -Argument "-NoProfile -File `"$briefScript`"$dryRunArg" -At $BriefTime

Register-WeekdayLoop -TaskName "jarvis-heartbeat-preclose-framing-brief" `
    -Argument "-NoProfile -File `"$hbScript`" -LoopName preclose-framing-brief -MaxAgeHours $MaxAgeHours" `
    -At $WatchTime

Write-Host "`nDone. Verify with:  Get-ScheduledTask -TaskName jarvis-*preclose-framing-brief*"
Write-Host "Test now with:      Start-ScheduledTask -TaskName jarvis-preclose-framing-brief"
