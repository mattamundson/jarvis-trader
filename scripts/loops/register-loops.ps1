<#
.SYNOPSIS
  One command to schedule the recommended jarvis-trader loops on Windows:
  the daily morning brief plus its dead-man heartbeat watcher. Idempotent.

.DESCRIPTION
  Implements the "if you do nothing else" recommendation from
  docs/loop-engineering-quickstart.md:
    - jarvis-morning-brief    daily at -BriefTime, runs morning-brief-loop.ps1
    - jarvis-heartbeat-brief  daily at -WatchTime, alerts if the brief stalled

  Re-running re-registers cleanly (unregisters same-named tasks first), so this
  is safe to run repeatedly. Optionally persists JARVIS_LOOP_WEBHOOK at user
  scope so scheduled (non-interactive) runs can send alerts.

  Run scripts\loops\preflight.ps1 FIRST. Requires an elevated shell to register
  scheduled tasks.

.EXAMPLE
  pwsh -File scripts\loops\register-loops.ps1
  pwsh -File scripts\loops\register-loops.ps1 -BriefTime 8:30am -LoopWebhook https://discord.com/api/webhooks/...
#>

[CmdletBinding()]
param(
    [string] $RepoRoot   = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string] $BriefTime  = "9am",      # when the morning brief runs
    [string] $WatchTime  = "12pm",     # when the heartbeat watcher runs
    [double] $MaxAgeHours = 26,         # stale threshold for the brief loop
    [string] $LoopWebhook = ""          # optional: persist JARVIS_LOOP_WEBHOOK (user scope)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$pwshExe   = (Get-Command pwsh -ErrorAction SilentlyContinue)?.Source
if (-not $pwshExe) { throw "pwsh.exe not found on PATH. Install PowerShell 7." }

$briefScript = Join-Path $RepoRoot "scripts\loops\morning-brief-loop.ps1"
$hbScript    = Join-Path $RepoRoot "scripts\loops\heartbeat-check.ps1"
foreach ($s in @($briefScript, $hbScript)) {
    if (-not (Test-Path $s)) { throw "missing script: $s" }
}

function Register-Loop {
    param([string] $TaskName, [string] $Argument, [string] $At)
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "[register] replaced existing task '$TaskName'"
    }
    $action  = New-ScheduledTaskAction  -Execute $pwshExe -Argument $Argument
    $trigger = New-ScheduledTaskTrigger  -Daily -At $At
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Description "jarvis-trader loop" | Out-Null
    Write-Host "[register] '$TaskName' -> daily $At"
}

# --- Optionally persist the alert webhook for non-interactive runs ------------
if (-not [string]::IsNullOrWhiteSpace($LoopWebhook)) {
    [Environment]::SetEnvironmentVariable("JARVIS_LOOP_WEBHOOK", $LoopWebhook, "User")
    $env:JARVIS_LOOP_WEBHOOK = $LoopWebhook
    Write-Host "[register] persisted JARVIS_LOOP_WEBHOOK (user scope)"
}

# --- The two recommended tasks ------------------------------------------------
Register-Loop -TaskName "jarvis-morning-brief" `
    -Argument "-NoProfile -File `"$briefScript`"" -At $BriefTime

Register-Loop -TaskName "jarvis-heartbeat-brief" `
    -Argument "-NoProfile -File `"$hbScript`" -LoopName morning-brief -MaxAgeHours $MaxAgeHours" `
    -At $WatchTime

Write-Host "`nDone. Verify with:  Get-ScheduledTask -TaskName jarvis-*"
Write-Host "Test now with:      Start-ScheduledTask -TaskName jarvis-morning-brief"
