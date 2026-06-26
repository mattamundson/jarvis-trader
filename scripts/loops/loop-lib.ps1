<#
.SYNOPSIS
  Shared helpers for jarvis-trader autonomous loop wrappers.

.DESCRIPTION
  Dot-source this from a loop script:  . "$PSScriptRoot\loop-lib.ps1"

  Provides the two brakes every unattended loop needs (see the loop-brakes
  skill): a dead-man heartbeat and a best-effort notification. Both are
  side-effect-only and never throw — a loop must not die because telemetry
  failed.

  Notification follows the repo's existing convention (notifications/
  discord_webhook.py): default-OFF unless an env var holds a webhook URL,
  best-effort with a short timeout, standard Discord {"content": ...} payload.

  Environment:
    JARVIS_LOOP_WEBHOOK   full Discord/Slack-style webhook URL (optional).
                          When unset, Send-LoopNotification is a no-op.
#>

Set-StrictMode -Version Latest

$script:LoopReportDir = $null   # set by Initialize-LoopPaths

function Initialize-LoopPaths {
    <# Resolve and create docs/loop-reports under the repo root. #>
    param([Parameter(Mandatory)][string] $RepoRoot)
    $script:LoopReportDir = Join-Path $RepoRoot "docs\loop-reports"
    if (-not (Test-Path $script:LoopReportDir)) {
        New-Item -ItemType Directory -Path $script:LoopReportDir -Force | Out-Null
    }
    return $script:LoopReportDir
}

function Write-LoopHeartbeat {
    <#
      Append a heartbeat line for $LoopName. heartbeat-check.ps1 reads the most
      recent line per loop to detect a loop that has silently stopped firing.
    #>
    param(
        [Parameter(Mandatory)][string] $LoopName,
        [Parameter(Mandatory)][string] $Status   # GREEN | RED | ERROR
    )
    if (-not $script:LoopReportDir) { return }
    $hb = Join-Path $script:LoopReportDir ".heartbeat"
    $stampUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    try {
        Add-Content -Path $hb -Value "$stampUtc`t$LoopName`t$Status" -Encoding UTF8
    } catch {
        Write-Warning "heartbeat write failed: $($_.Exception.Message)"
    }
}

function Send-LoopNotification {
    <# Best-effort one-line push. No-op (returns $false) when no webhook is set. #>
    param([Parameter(Mandatory)][string] $Message)
    $url = ($env:JARVIS_LOOP_WEBHOOK | Out-String).Trim()
    if ([string]::IsNullOrWhiteSpace($url)) {
        Write-Host "[loop-lib] JARVIS_LOOP_WEBHOOK unset; skipping notification."
        return $false
    }
    try {
        $body = @{ content = $Message } | ConvertTo-Json -Compress
        Invoke-RestMethod -Uri $url -Method Post -ContentType "application/json" `
            -Body $body -TimeoutSec 5 | Out-Null
        return $true
    } catch {
        Write-Warning "notification failed (non-fatal): $($_.Exception.Message)"
        return $false
    }
}
