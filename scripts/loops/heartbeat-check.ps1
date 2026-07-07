<#
.SYNOPSIS
  Dead-man watcher for jarvis-trader loops. Alerts if a loop's last heartbeat is
  older than the allowed age — the cure for the "silent death" failure mode where
  a scheduled loop stops firing and nobody notices.

.DESCRIPTION
  Reads docs/loop-reports/.heartbeat (written by loop-lib.ps1 Write-LoopHeartbeat),
  finds the most recent entry for $LoopName, and:
    - exits 0 and stays quiet if the heartbeat is fresh,
    - exits 1 and sends a notification if it is stale or missing.

  Schedule this on a SEPARATE, more frequent Task Scheduler trigger than the loop
  it watches, so a watcher run does not depend on the loop it is checking.

  Exit codes:
    0  fresh    — last heartbeat within -MaxAgeHours
    1  STALE    — heartbeat too old or missing (notification sent)

.EXAMPLE
  pwsh -File heartbeat-check.ps1 -LoopName triage -MaxAgeHours 26
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $LoopName,
    [double] $MaxAgeHours = 26,                                    # daily loop + grace
    [string] $RepoRoot    = (Resolve-Path "$PSScriptRoot\..\..").Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\loop-lib.ps1"
$reportDir = Initialize-LoopPaths -RepoRoot $RepoRoot
$hb = Join-Path $reportDir ".heartbeat"

function Invoke-StaleAlert {
    param([string] $Reason)
    $msg = "[!!] jarvis loop '$LoopName' heartbeat STALE - $Reason (max ${MaxAgeHours}h)"
    Send-LoopNotification -Message $msg | Out-Null
    Write-Warning $msg
    exit 1
}

if (-not (Test-Path $hb)) { Invoke-StaleAlert -Reason "no heartbeat file yet" }

# Last line for this loop:  <utc>\t<loop>\t<status>
$last = Get-Content -Path $hb -Encoding UTF8 |
        Where-Object { $_ -match "`t$([regex]::Escape($LoopName))`t" } |
        Select-Object -Last 1

if (-not $last) { Invoke-StaleAlert -Reason "no heartbeat recorded for this loop" }

$stampStr = ($last -split "`t")[0]
try {
    $stamp = [datetime]::Parse($stampStr, $null, [System.Globalization.DateTimeStyles]::AdjustToUniversal)
} catch {
    Invoke-StaleAlert -Reason "unparseable heartbeat timestamp '$stampStr'"
}

$ageHours = ((Get-Date).ToUniversalTime() - $stamp).TotalHours
if ($ageHours -gt $MaxAgeHours) {
    Invoke-StaleAlert -Reason ("last run {0:N1}h ago" -f $ageHours)
}

Write-Host ("[heartbeat-check] '{0}' OK - last run {1:N1}h ago" -f $LoopName, $ageHours)
exit 0
