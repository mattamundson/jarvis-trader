# install-discord-obsidian-sync-task.ps1 -- Register Windows Task Scheduler task
# "Jarvis-DiscordObsidianSync" to run discord-obsidian-sync.ps1 daily at 02:30.
#
# Syncs last 7 days of corey_session_bias from jarvis_trader.db into the
# Obsidian second-brain vault at master-jarvis/second-brain/trading/discord/.
#
# Idempotent: deletes any prior registration before re-creating.
# No admin required -- runs under the current interactive user account.
#
# Usage:
#   pwsh -NoProfile -File scripts/install-discord-obsidian-sync-task.ps1
#
# Verify after registration:
#   schtasks /Query /TN "Jarvis-DiscordObsidianSync" /FO LIST

$ErrorActionPreference = "Stop"

$taskName   = "Jarvis-DiscordObsidianSync"
$psScript   = "C:\Users\mattm\master-jarvis\scripts\discord-obsidian-sync.ps1"
$workingDir = "C:\Users\mattm\master-jarvis"
$pwshCmd = Get-Command pwsh -ErrorAction SilentlyContinue
$pwsh    = if ($pwshCmd) { $pwshCmd.Source } else { "pwsh" }

# -- Pre-flight ---------------------------------------------------------------
if (-not (Test-Path $psScript)) {
    Write-Host "ERROR: discord-obsidian-sync.ps1 not found at $psScript"
    exit 1
}

Write-Host "Registering task: $taskName"
Write-Host "  Script : $psScript"
Write-Host "  Trigger: daily 02:30 AM local time"
Write-Host ""

# -- Remove prior registration (idempotent) -----------------------------------
try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
} catch {}

# -- Build task components ----------------------------------------------------
$action = New-ScheduledTaskAction `
    -Execute $pwsh `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$psScript`"" `
    -WorkingDirectory $workingDir

$trigger = New-ScheduledTaskTrigger -Daily -At "02:30AM"

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
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
    -Description "Sync last 7 days of Corey session bias from jarvis_trader.db into Obsidian second-brain vault at second-brain/trading/discord/" `
    | Out-Null

Write-Host "Registered: $taskName"
Write-Host ""
Write-Host "Verify:"
Write-Host "  schtasks /Query /TN `"$taskName`" /FO LIST"
Write-Host ""
Write-Host "Dry-run now (optional):"
Write-Host "  Start-ScheduledTask -TaskName `"$taskName`""
