<#
.SYNOPSIS
  jarvis-trader daily morning-brief loop. Generates the go/no-go brief via the
  existing engine/scripts/daily_morning_briefing.py (which posts to Discord
  itself), with the standard loop brakes: health pre-check, heartbeat, graceful
  fail-closed, and notification on failure only.

.DESCRIPTION
  This is the recommended FIRST scheduled loop: pure read + report, touches no
  orders and no safety code. It fails CLOSED — if the engine is down it does not
  silently "succeed"; it heartbeats ERROR, alerts, and exits non-zero so Task
  Scheduler shows red.

  On success the briefing itself is the notification (the Python script posts to
  Discord via DISCORD_WEBHOOK_URL), so this wrapper does NOT double-post; it only
  sends a loop notification when something goes wrong.

  Exit codes:
    0  OK     — brief generated
    3  ERROR  — engine down or generator failed (notification sent)

.NOTES
  Requires the engine venv at engine/.venv/Scripts/python and the engine running
  on port 8010. Set DISCORD_WEBHOOK_URL for the brief, JARVIS_LOOP_WEBHOOK for
  failure alerts. Companion: docs/loop-engineering-quickstart.md.

  Every ERROR exit also appends "<UTC timestamp>`t<reason>" to
  docs/loop-reports/morning-brief.log so the failure reason survives after the
  Task Scheduler run ends (the .heartbeat file alone only records ERROR, not why).
#>

[CmdletBinding()]
param(
    [string] $RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string] $HealthUrl = "http://127.0.0.1:8010/health"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\loop-lib.ps1"
Initialize-LoopPaths -RepoRoot $RepoRoot | Out-Null
$loopName = "morning-brief"
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$venvPython = Join-Path $RepoRoot "engine\.venv\Scripts\python.exe"

function Stop-WithError {
    param([string] $Reason)
    Write-LoopHeartbeat -LoopName $loopName -Status "ERROR"
    if ($script:LoopReportDir) {
        try {
            $failLog = Join-Path $script:LoopReportDir "morning-brief.log"
            $stampUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
            Add-Content -Path $failLog -Value "$stampUtc`t$Reason" -Encoding UTF8
        }
        catch {
            Write-Warning "failure log write failed (non-fatal): $($_.Exception.Message)"
        }
    }
    Send-LoopNotification -Message "[!!] jarvis morning-brief FAILED - $Reason ($stamp)" | Out-Null
    Write-Warning "[morning-brief-loop] ERROR - $Reason"
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

# --- Generate the brief (the module posts to Discord itself) ------------------
Write-Host "[morning-brief-loop] generating daily brief..."
Push-Location $RepoRoot
try {
    & $venvPython -m engine.scripts.daily_morning_briefing
    $code = $LASTEXITCODE
}
catch {
    Pop-Location
    Stop-WithError -Reason "generator threw: $($_.Exception.Message)"
}
Pop-Location

if ($code -ne 0) { Stop-WithError -Reason "generator exited $code" }

Write-LoopHeartbeat -LoopName $loopName -Status "GREEN"
Write-Host "[morning-brief-loop] OK - brief generated and posted ($stamp)"
exit 0
