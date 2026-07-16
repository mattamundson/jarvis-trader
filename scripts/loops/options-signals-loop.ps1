<#
.SYNOPSIS
  jarvis-trader options-signals loop. Runs engine/scripts/options_signals_snapshot.py
  every 30 minutes (RTH-gated inside the Python script) to refresh the SPY/QQQ
  market-implied snapshot behind the /signals dashboard Options section.

.DESCRIPTION
  Read-only pipeline: public CBOE data in, local JSON out. No orders, no
  Discord, no engine dependency.

  DELIBERATE DEVIATION from the framing-brief loop: there is NO engine /health
  pre-check. The generator never talks to the engine -- it fetches CBOE and
  writes a file the engine merely serves -- so failing closed on engine-down
  would pointlessly stop snapshot accumulation while the engine restarts.

  Exit mapping:
    generator 0 (ok, or outside-RTH skip)  -> heartbeat GREEN, exit 0
    generator 2 (partial/degraded)         -> heartbeat GREEN + one warn
                                              notification, exit 0 (the partial
                                              snapshot still publishes and
                                              self-labels on the dashboard --
                                              a 30-min loop must not page red
                                              13x/day for one QQQ timeout)
    anything else / throw                  -> heartbeat ERROR, notify, exit 3

.NOTES
  Requires the engine venv at engine/.venv/Scripts/python. Set
  JARVIS_LOOP_WEBHOOK for alerts. Companion watcher: heartbeat-check.ps1
  -LoopName options-signals (see register-options-signals-loop.ps1).

.PARAMETER DryRun
  Passed through to options_signals_snapshot.py --dry-run: fetch + compute +
  print, write nothing. Manual-verification aid; the scheduled registration
  runs live-writing by design (see the register script).
#>

[CmdletBinding()]
param(
    [string] $RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [switch] $DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\loop-lib.ps1"
Initialize-LoopPaths -RepoRoot $RepoRoot | Out-Null
$loopName = "options-signals"
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$venvPython = Join-Path $RepoRoot "engine\.venv\Scripts\python.exe"

function Stop-WithError {
    param([string] $Reason)
    Write-LoopHeartbeat -LoopName $loopName -Status "ERROR"
    Send-LoopNotification -Message "[!!] jarvis options-signals FAILED - $Reason ($stamp)" | Out-Null
    Write-Warning "[options-signals-loop] ERROR - $Reason"
    exit 3
}

if (-not (Test-Path $venvPython)) { Stop-WithError -Reason "venv python missing: $venvPython" }

$modeLabel = if ($DryRun) { "dry-run" } else { "live" }
Write-Host "[options-signals-loop] refreshing options snapshot ($modeLabel)..."
Push-Location $RepoRoot
try {
    if ($DryRun) {
        & $venvPython -m engine.scripts.options_signals_snapshot --dry-run
    }
    else {
        & $venvPython -m engine.scripts.options_signals_snapshot
    }
    $code = $LASTEXITCODE
}
catch {
    Pop-Location
    Stop-WithError -Reason "generator threw: $($_.Exception.Message)"
}
Pop-Location

if ($code -eq 2) {
    # Partial snapshot: published and self-labeled PARTIAL on the dashboard.
    # Warn once, stay green -- red is reserved for producing nothing at all.
    Write-LoopHeartbeat -LoopName $loopName -Status "GREEN"
    Send-LoopNotification -Message "[!] jarvis options-signals PARTIAL - one or more feeds degraded ($stamp)" | Out-Null
    Write-Host "[options-signals-loop] PARTIAL - snapshot published with degraded feeds ($stamp)"
    exit 0
}
if ($code -ne 0) { Stop-WithError -Reason "generator exited $code" }

Write-LoopHeartbeat -LoopName $loopName -Status "GREEN"
Write-Host "[options-signals-loop] OK ($modeLabel, $stamp)"
exit 0
