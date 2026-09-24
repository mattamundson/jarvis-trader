<#
.SYNOPSIS
  jarvis-trader weekly forecast-calibrator loop. Aggregates graded forecast
  history and updates the calibrator state JSON + report via
  engine/analytics/morning_levels_calibrator.py. Heartbeat, fail-closed, notify
  on failure only.

.DESCRIPTION
  Pure read + analysis: reads the forecast journal from the SQLite DB and writes
  data/morning_levels_calibrator_state.json (consumed by JARVIS's Read) plus a
  calibration report. Touches no orders and no safety code. DB-only, so it does
  NOT gate on engine HTTP health.

  Exit codes:
    0  OK     - calibration updated
    3  ERROR  - calibrator failed (notification sent)

.NOTES
  Requires the engine venv at engine/.venv/Scripts/python. Set
  JARVIS_LOOP_WEBHOOK for failure alerts.

  Every ERROR exit also appends "<UTC timestamp>`t<reason>" to
  docs/loop-reports/levels-calibrator.log so the failure reason survives
  after the Task Scheduler run ends (the .heartbeat file alone only records
  ERROR, not why). Same fix as morning-brief-loop.ps1 (2026-07-09).
#>

[CmdletBinding()]
param(
    [string] $RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [int]    $Days = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\loop-lib.ps1"
Initialize-LoopPaths -RepoRoot $RepoRoot | Out-Null
$loopName = "levels-calibrator"
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$venvPython = Join-Path $RepoRoot "engine\.venv\Scripts\python.exe"

function Stop-WithError {
    param([string] $Reason)
    Write-LoopHeartbeat -LoopName $loopName -Status "ERROR"
    if ($script:LoopReportDir) {
        try {
            $failLog = Join-Path $script:LoopReportDir "levels-calibrator.log"
            $stampUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
            Add-Content -Path $failLog -Value "$stampUtc`t$Reason" -Encoding UTF8
        }
        catch {
            Write-Warning "failure log write failed (non-fatal): $($_.Exception.Message)"
        }
    }
    Send-LoopNotification -Message "[!!] jarvis levels-calibrator FAILED - $Reason ($stamp)" | Out-Null
    Write-Warning "[levels-calibrator-loop] ERROR - $Reason"
    exit 3
}

if (-not (Test-Path $venvPython)) { Stop-WithError -Reason "venv python missing: $venvPython" }

Write-Host "[levels-calibrator-loop] recalibrating from last $Days days..."
Push-Location $RepoRoot
try {
    & $venvPython -m engine.analytics.morning_levels_calibrator --days $Days
    $code = $LASTEXITCODE
}
catch {
    Pop-Location
    Stop-WithError -Reason "calibrator threw: $($_.Exception.Message)"
}
Pop-Location

if ($code -ne 0) { Stop-WithError -Reason "calibrator exited $code" }

Write-LoopHeartbeat -LoopName $loopName -Status "GREEN"
Write-Host "[levels-calibrator-loop] OK - calibration updated ($stamp)"
exit 0
