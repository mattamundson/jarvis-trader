# ============================================================
# JARVIS API — Windows Task Scheduler Auto-Start
# Run this ONCE as Administrator to register a scheduled task
# that starts the API on every Windows login automatically.
# ============================================================
# Usage (PowerShell as Administrator):
#   .\deploy\AUTOSTART_WINDOWS.ps1

$TaskName  = "JARVIS-API-Bridge"
$WorkDir   = "C:\Users\mattm\workspace\jarvis_api"
$ScriptPath = "$WorkDir\deploy\START_WINDOWS.ps1"

# Remove existing task if present
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# Build the action: run the start script on login
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -NonInteractive -ExecutionPolicy Bypass -File `"$ScriptPath`" start" `
    -WorkingDirectory $WorkDir

# Trigger: at logon of current user
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# Settings: allow running whether or not user is logged on, restart on failure
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -RunOnlyIfNetworkAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -RunLevel Highest `
    -Force

Write-Host "`n[JARVIS] Scheduled task '$TaskName' registered." -ForegroundColor Green
Write-Host "         Starts automatically at every Windows login." -ForegroundColor Green
Write-Host "`nTo manage the task:" -ForegroundColor Cyan
Write-Host "  Start now : Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Stop      : Stop-ScheduledTask  -TaskName '$TaskName'"
Write-Host "  Remove    : Unregister-ScheduledTask -TaskName '$TaskName'"
Write-Host "  View logs : Get-Content '$WorkDir\logs\jarvis_api.log' -Tail 20"
