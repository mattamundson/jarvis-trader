<#
.SYNOPSIS
  jarvis-trader evening forecast-scorer loop. Grades the morning forecast
  (levels + JARVIS's Read) against the realized session via
  engine/scripts/forecast_outcome_scorer.py, which posts a scoreline to Discord
  itself. Standard loop brakes: heartbeat, fail-closed, notify on failure only.

.DESCRIPTION
  Pure read + report: reads bars + the forecast journal from the SQLite DB,
  writes outcomes back, emits a scorecard, and posts to Discord. Touches no
  orders and no safety code. DB-only, so it does NOT gate on engine HTTP health.

  Exit codes:
    0  OK     - forecast scored
    3  ERROR  - scorer failed (notification sent)

.NOTES
  Requires the engine venv at engine/.venv/Scripts/python. Set
  DISCORD_WEBHOOK_URL for the scoreline, JARVIS_LOOP_WEBHOOK for failure alerts.

  Every ERROR exit also appends "<UTC timestamp>`t<reason>" to
  docs/loop-reports/forecast-scorer.log so the failure reason survives after
  the Task Scheduler run ends (the .heartbeat file alone only records ERROR,
  not why). Same fix as morning-brief-loop.ps1 (2026-07-09).
#>

[CmdletBinding()]
param(
    [string] $RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\loop-lib.ps1"
Initialize-LoopPaths -RepoRoot $RepoRoot | Out-Null
$loopName = "forecast-scorer"
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$venvPython = Join-Path $RepoRoot "engine\.venv\Scripts\python.exe"

function Stop-WithError {
    param([string] $Reason)
    Write-LoopHeartbeat -LoopName $loopName -Status "ERROR"
    if ($script:LoopReportDir) {
        try {
            $failLog = Join-Path $script:LoopReportDir "forecast-scorer.log"
            $stampUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
            Add-Content -Path $failLog -Value "$stampUtc`t$Reason" -Encoding UTF8
        }
        catch {
            Write-Warning "failure log write failed (non-fatal): $($_.Exception.Message)"
        }
    }
    Send-LoopNotification -Message "[!!] jarvis forecast-scorer FAILED - $Reason ($stamp)" | Out-Null
    Write-Warning "[forecast-scorer-loop] ERROR - $Reason"
    exit 3
}

if (-not (Test-Path $venvPython)) { Stop-WithError -Reason "venv python missing: $venvPython" }

Write-Host "[forecast-scorer-loop] scoring today's forecast..."
Push-Location $RepoRoot
try {
    & $venvPython -m engine.scripts.forecast_outcome_scorer
    $code = $LASTEXITCODE
}
catch {
    Pop-Location
    Stop-WithError -Reason "scorer threw: $($_.Exception.Message)"
}
Pop-Location

if ($code -ne 0) { Stop-WithError -Reason "scorer exited $code" }

Write-LoopHeartbeat -LoopName $loopName -Status "GREEN"
Write-Host "[forecast-scorer-loop] OK - forecast scored ($stamp)"
exit 0
