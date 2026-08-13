<#
.SYNOPSIS
  jarvis-trader LONG_GAP_FILL options paper-track loop. Runs
  engine/scripts/gapfill_options_papertrack.py every 15 minutes (RTH-gated
  inside the Python script) to record REAL delayed CBOE SPY quotes for the
  call-spread expression of each live LONG_GAP_FILL paper trade.

.DESCRIPTION
  Instrumentation only: reads the paper_trades DB read-only, fetches public
  CBOE quotes, appends engine/data/options_signals/gapfill_papertrack.jsonl.
  No orders, no execution wiring -- per the June-2026 no-validated-options-edge
  rule the series goes to the options gate after n>=30 completed records, and
  nothing trades without a PASS and Amo's authorization.

  Same deliberate deviation as options-signals-loop.ps1: no engine /health
  pre-check (the script never talks to the engine).

  Exit mapping:
    logger 0 (ok / RTH-skip / nothing to do)  -> heartbeat GREEN, exit 0
    logger 2 (chain fetch degraded, retryable) -> heartbeat GREEN + warn, exit 0
    anything else / throw                      -> heartbeat ERROR, notify, exit 3

.PARAMETER DryRun
  Passed through to gapfill_options_papertrack.py --dry-run: compute + print,
  write nothing.
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
$loopName = "gapfill-papertrack"
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$venvPython = Join-Path $RepoRoot "engine\.venv\Scripts\python.exe"

function Stop-WithError {
    param([string] $Reason)
    Write-LoopHeartbeat -LoopName $loopName -Status "ERROR"
    Send-LoopNotification -Message "[!!] jarvis gapfill-papertrack FAILED - $Reason ($stamp)" | Out-Null
    Write-Warning "[gapfill-papertrack-loop] ERROR - $Reason"
    exit 3
}

if (-not (Test-Path $venvPython)) { Stop-WithError -Reason "venv python missing: $venvPython" }

$modeLabel = if ($DryRun) { "dry-run" } else { "live" }
Write-Host "[gapfill-papertrack-loop] reconciling paper-track records ($modeLabel)..."
Push-Location $RepoRoot
try {
    if ($DryRun) {
        & $venvPython -m engine.scripts.gapfill_options_papertrack --dry-run
    }
    else {
        & $venvPython -m engine.scripts.gapfill_options_papertrack
    }
    $code = $LASTEXITCODE
}
catch {
    Pop-Location
    Stop-WithError -Reason "logger threw: $($_.Exception.Message)"
}
Pop-Location

if ($code -eq 2) {
    # Chain fetch failed with pending work -- records stay pending and the next
    # fire retries. Warn once, stay green.
    Write-LoopHeartbeat -LoopName $loopName -Status "GREEN"
    Send-LoopNotification -Message "[!] jarvis gapfill-papertrack DEGRADED - CBOE fetch failed, will retry ($stamp)" | Out-Null
    Write-Host "[gapfill-papertrack-loop] DEGRADED - retry next fire ($stamp)"
    exit 0
}
if ($code -ne 0) { Stop-WithError -Reason "logger exited $code" }

Write-LoopHeartbeat -LoopName $loopName -Status "GREEN"
Write-Host "[gapfill-papertrack-loop] OK ($modeLabel, $stamp)"
exit 0
