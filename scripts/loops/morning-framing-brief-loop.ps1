<#
.SYNOPSIS
  jarvis-trader morning-framing-brief loop. Generates the automated Corey-style
  AMT framing brief for ES/NQ via engine/scripts/morning_framing_brief.py (which
  posts to Discord itself and writes the dashboard's /framing-brief source
  file), with the standard loop brakes: health pre-check, heartbeat, graceful
  fail-closed, and notification on failure only.

.DESCRIPTION
  Pure read + LLM-synthesis + report; touches no orders and no safety code.
  Fails CLOSED — if the engine is down it does not silently "succeed"; it
  heartbeats ERROR, alerts, and exits non-zero so Task Scheduler shows red.
  The Python script itself exits non-zero (code 2) when the brief generation
  degraded to a fallback stub (LLM failure, malformed output) — this wrapper
  treats that identically to a hard failure, so a degraded brief never posts
  silently.

  On success the brief generation is the notification (the Python script posts
  chunked to Discord via DISCORD_WEBHOOK_URL when not run with -DryRun), so
  this wrapper does NOT double-post; it only sends a loop notification when
  something goes wrong.

  Exit codes:
    0  OK     — brief generated (and posted, unless -DryRun)
    3  ERROR  — engine down or generator failed/degraded (notification sent)

.NOTES
  Requires the engine venv at engine/.venv/Scripts/python and the engine
  running on port 8010. Set DISCORD_WEBHOOK_URL for the brief,
  JARVIS_LOOP_WEBHOOK for failure alerts. Companion watcher: register with
  heartbeat-check.ps1 -LoopName morning-framing-brief (see
  register-framing-brief-loop.ps1).

.PARAMETER DryRun
  Passed straight through to morning_framing_brief.py --dry-run: generates and
  saves the brief but never posts to Discord. Use during the rollout gating
  period (recommended 5-10 trading days) before trusting live auto-post.
#>

[CmdletBinding()]
param(
    [string] $RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string] $HealthUrl = "http://127.0.0.1:8010/health",
    [switch] $DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\loop-lib.ps1"
Initialize-LoopPaths -RepoRoot $RepoRoot | Out-Null
$loopName = "morning-framing-brief"
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$venvPython = Join-Path $RepoRoot "engine\.venv\Scripts\python.exe"

function Stop-WithError {
    param([string] $Reason)
    Write-LoopHeartbeat -LoopName $loopName -Status "ERROR"
    Send-LoopNotification -Message "[!!] jarvis morning-framing-brief FAILED - $Reason ($stamp)" | Out-Null
    Write-Warning "[morning-framing-brief-loop] ERROR - $Reason"
    exit 3
}

# --- Fail closed if the engine is unreachable ---------------------------------
try {
    $resp = Invoke-WebRequest -Uri $HealthUrl -TimeoutSec 5 -UseBasicParsing
    if ($resp.StatusCode -ne 200) { Stop-WithError -Reason "health HTTP $($resp.StatusCode)" }
}
catch {
    Stop-WithError -Reason "engine unreachable at $HealthUrl"
}

if (-not (Test-Path $venvPython)) { Stop-WithError -Reason "venv python missing: $venvPython" }

# --- Generate the brief (the module posts to Discord itself unless -DryRun) --
$modeLabel = if ($DryRun) { "dry-run" } else { "live" }
Write-Host "[morning-framing-brief-loop] generating framing brief ($modeLabel)..."
Push-Location $RepoRoot
try {
    if ($DryRun) {
        & $venvPython -m engine.scripts.morning_framing_brief --dry-run
    }
    else {
        & $venvPython -m engine.scripts.morning_framing_brief
    }
    $code = $LASTEXITCODE
}
catch {
    Pop-Location
    Stop-WithError -Reason "generator threw: $($_.Exception.Message)"
}
Pop-Location

if ($code -ne 0) { Stop-WithError -Reason "generator exited $code (degraded or failed)" }

Write-LoopHeartbeat -LoopName $loopName -Status "GREEN"
Write-Host "[morning-framing-brief-loop] OK - brief generated ($modeLabel, $stamp)"
exit 0
