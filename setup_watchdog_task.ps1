# =============================================================================
# JARVIS Engine Watchdog — Task Scheduler Setup
# =============================================================================
# Run this ONCE as Administrator to register the watchdog as a Windows
# Scheduled Task that auto-starts on login and restarts if it crashes.
#
# Usage:
#   Right-click PowerShell -> "Run as Administrator"
#   .\setup_watchdog_task.ps1
#
# To start immediately after registering:
#   Start-ScheduledTask -TaskName "JARVIS Engine Watchdog"
#
# To check status:
#   Get-ScheduledTask -TaskName "JARVIS Engine Watchdog"
#
# To remove:
#   Unregister-ScheduledTask -TaskName "JARVIS Engine Watchdog" -Confirm:$false
# =============================================================================

$TaskName    = "JARVIS Engine Watchdog"
$ScriptPath  = "C:\Users\mattm\ThinkorSwim\jarvis-trader\watchdog_engine.ps1"
$WorkingDir  = "C:\Users\mattm\ThinkorSwim\jarvis-trader"

Write-Host ""
Write-Host "JARVIS Engine Watchdog — Task Scheduler Setup" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# Verify the watchdog script exists before registering
if (-not (Test-Path $ScriptPath)) {
    Write-Host "ERROR: Watchdog script not found at:" -ForegroundColor Red
    Write-Host "  $ScriptPath" -ForegroundColor Red
    Write-Host "Run this script from the jarvis-trader directory after creating watchdog_engine.ps1" -ForegroundColor Yellow
    exit 1
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`"" `
    -WorkingDirectory $WorkingDir

# Trigger: At startup (so watchdog survives reboots)
$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable $true `
    -RunOnlyIfNetworkAvailable $false

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Monitors JARVIS trading engine health. Auto-restarts engine if /health fails 3 consecutive times. Sends WhatsApp alert if restart fails." `
        -Force | Out-Null

    Write-Host ""
    Write-Host "SUCCESS: Task '$TaskName' registered." -ForegroundColor Green
    Write-Host ""
    Write-Host "The watchdog will auto-start on next login/reboot." -ForegroundColor White
    Write-Host ""
    Write-Host "To start the watchdog NOW without rebooting:" -ForegroundColor Yellow
    Write-Host "  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "To check status:" -ForegroundColor Yellow
    Write-Host "  Get-ScheduledTask -TaskName '$TaskName' | Select-Object TaskName, State" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "To view watchdog log:" -ForegroundColor Yellow
    Write-Host "  Get-Content C:\Users\mattm\ThinkorSwim\jarvis-trader\watchdog.log -Tail 50" -ForegroundColor Cyan
    Write-Host ""

    # Offer to start immediately
    $startNow = Read-Host "Start watchdog now? [Y/n]"
    if ($startNow -eq "" -or $startNow -match "^[Yy]") {
        Start-ScheduledTask -TaskName $TaskName
        Start-Sleep -Seconds 2
        $task = Get-ScheduledTask -TaskName $TaskName
        Write-Host "Watchdog state: $($task.State)" -ForegroundColor Green
    }

} catch {
    Write-Host ""
    Write-Host "ERROR registering task: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    Write-Host "Make sure you are running PowerShell as Administrator." -ForegroundColor Yellow
    exit 1
}
