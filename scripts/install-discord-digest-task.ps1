# install-discord-digest-task.ps1 -- Register Windows Task Scheduler task
# "Jarvis-DiscordGitDigest" to run discord-github-digest.ps1 daily at 03:00.
#
# Generates a daily Discord intelligence digest JSON (session bias, sentiment,
# top signals) and commits it to the jarvis-trader git repo.
#
# Runs after Jarvis-DiscordObsidianSync (02:30) so session bias is fresh.
#
# Idempotent: deletes any prior registration before re-creating.
# No admin required -- runs under the current interactive user account.
#
# Usage:
#   pwsh -NoProfile -File scripts/install-discord-digest-task.ps1
#
# Verify after registration:
#   schtasks /Query /TN "Jarvis-DiscordGitDigest" /FO LIST

$ErrorActionPreference = "Stop"

$taskName   = "Jarvis-DiscordGitDigest"
$repoRoot   = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$psScript   = Join-Path $repoRoot "scripts\discord-github-digest.ps1"
$pwshCmd = Get-Command pwsh -ErrorAction SilentlyContinue
$pwsh    = if ($pwshCmd) { $pwshCmd.Source } else { "pwsh" }

# -- Pre-flight ---------------------------------------------------------------
if (-not (Test-Path $psScript)) {
    Write-Host "ERROR: discord-github-digest.ps1 not found at $psScript"
    exit 1
}

Write-Host "Registering task: $taskName"
Write-Host "  Script : $psScript"
Write-Host "  Trigger: daily 03:00 AM local time"
Write-Host ""

# -- Remove prior registration (idempotent) -----------------------------------
try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
} catch {}

# -- Build task components ----------------------------------------------------
$action = New-ScheduledTaskAction `
    -Execute $pwsh `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$psScript`"" `
    -WorkingDirectory $repoRoot

$trigger = New-ScheduledTaskTrigger -Daily -At "03:00AM"

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Generate daily Discord intelligence digest JSON (session bias, sentiment, top signals) and commit to jarvis-trader git repo" `
    | Out-Null

Write-Host "Registered: $taskName"
Write-Host ""
Write-Host "Verify:"
Write-Host "  schtasks /Query /TN `"$taskName`" /FO LIST"
Write-Host ""
Write-Host "Dry-run now (optional):"
Write-Host "  Start-ScheduledTask -TaskName `"$taskName`""
