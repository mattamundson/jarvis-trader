# Register the JarvisTrader_OvernightStatus scheduled task.
#
# The task runs engine/scripts/overnight_status.py daily at 07:00 local time,
# writing $HOME\overnight_status.html for morning eyeball review.
#
# Idempotent: unregisters any prior task with the same name before re-creating.
#
# Usage (no admin required, runs under current user):
#   pwsh -NoProfile -File scripts/register_overnight_status_task.ps1

$ErrorActionPreference = "Stop"

$taskName  = "JarvisTrader_OvernightStatus"
$repoRoot  = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $repoRoot "engine\.venv\Scripts\python.exe"
$script    = Join-Path $repoRoot "engine\scripts\overnight_status.py"

if (-not (Test-Path $pythonExe)) {
    Write-Host "ERROR: venv python not found at $pythonExe"
    exit 1
}
if (-not (Test-Path $script)) {
    Write-Host "ERROR: overnight_status.py not found at $script"
    exit 1
}

# Remove any prior registration so this script stays idempotent.
try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
} catch {}

$action    = New-ScheduledTaskAction -Execute $pythonExe -Argument "`"$script`"" -WorkingDirectory $repoRoot
$trigger   = New-ScheduledTaskTrigger -Daily -At 7:00AM
$settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Render overnight-automation health HTML to $env:USERPROFILE\overnight_status.html daily at 07:00 local." | Out-Null

Write-Host "Registered: $taskName (daily 07:00 local)"
Write-Host "  Script : $script"
Write-Host "  Python : $pythonExe"
Write-Host "  Output : $env:USERPROFILE\overnight_status.html"
Write-Host ""
Write-Host "Dry-run it now:"
Write-Host "  Start-ScheduledTask -TaskName $taskName"
Write-Host "  Get-ScheduledTaskInfo -TaskName $taskName | Format-List LastRunTime, LastTaskResult"
