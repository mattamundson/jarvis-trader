<#
.SYNOPSIS
  Register the self-improving morning-briefing loop's two new scheduled tasks:
    - jarvis-forecast-scorer    daily at -ScoreTime (post-close), grades the day
    - jarvis-levels-calibrator  weekly on -CalibrateDay at -CalibrateTime
  Idempotent: re-running unregisters same-named tasks first. Requires an elevated
  shell to register scheduled tasks.

.DESCRIPTION
  Companion to register-loops.ps1 (which registers jarvis-morning-brief). The
  morning brief writes the forecast pre-open; the scorer grades it post-close;
  the calibrator rolls up graded history weekly so the Read self-corrects.

  Battery flags are cleared (AllowStartIfOnBatteries / DontStopIfGoingOnBatteries)
  so a laptop on battery does not silently refuse the task (0x800710E0).

.EXAMPLE
  pwsh -File scripts\loops\register-forecast-tasks.ps1
  pwsh -File scripts\loops\register-forecast-tasks.ps1 -ScoreTime 4:15pm -CalibrateDay Sunday -CalibrateTime 5pm
#>

[CmdletBinding()]
param(
    [string] $RepoRoot     = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string] $ScoreTime    = "4:15pm",    # post-close (RTH close 4:00pm ET)
    [string] $CalibrateDay = "Sunday",    # weekly calibration day
    [string] $CalibrateTime= "5pm"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$pwshExe = (Get-Command pwsh -ErrorAction SilentlyContinue)?.Source
if (-not $pwshExe) { throw "pwsh.exe not found on PATH. Install PowerShell 7." }

$scorerScript = Join-Path $RepoRoot "scripts\loops\forecast-scorer-loop.ps1"
$calibScript  = Join-Path $RepoRoot "scripts\loops\levels-calibrator-loop.ps1"
foreach ($s in @($scorerScript, $calibScript)) {
    if (-not (Test-Path $s)) { throw "missing script: $s" }
}

function New-LoopSettings {
    # StartWhenAvailable catches up missed runs; battery flags avoid 0x800710E0.
    New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
}

function Register-DailyTask {
    param([string] $TaskName, [string] $Argument, [string] $At)
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "[register] replaced existing task '$TaskName'"
    }
    $action  = New-ScheduledTaskAction  -Execute $pwshExe -Argument $Argument
    $trigger = New-ScheduledTaskTrigger  -Daily -At $At
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings (New-LoopSettings) -Description "jarvis-trader self-improving brief loop" | Out-Null
    Write-Host "[register] '$TaskName' -> daily $At"
}

function Register-WeeklyTask {
    param([string] $TaskName, [string] $Argument, [string] $Day, [string] $At)
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "[register] replaced existing task '$TaskName'"
    }
    $action  = New-ScheduledTaskAction  -Execute $pwshExe -Argument $Argument
    $trigger = New-ScheduledTaskTrigger  -Weekly -DaysOfWeek $Day -At $At
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings (New-LoopSettings) -Description "jarvis-trader self-improving brief loop" | Out-Null
    Write-Host "[register] '$TaskName' -> weekly $Day $At"
}

Register-DailyTask -TaskName "jarvis-forecast-scorer" `
    -Argument "-NoProfile -File `"$scorerScript`"" -At $ScoreTime

Register-WeeklyTask -TaskName "jarvis-levels-calibrator" `
    -Argument "-NoProfile -File `"$calibScript`"" -Day $CalibrateDay -At $CalibrateTime

Write-Host "`nDone. Verify with:  Get-ScheduledTask -TaskName jarvis-forecast-scorer, jarvis-levels-calibrator"
Write-Host "Test now with:      Start-ScheduledTask -TaskName jarvis-forecast-scorer"
