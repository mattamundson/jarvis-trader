#Requires -Version 5.1
<#
.SYNOPSIS
  Installs the Jarvis-EngineWatchdog scheduled task (runs every 5 minutes).

.NOTES
  Run once. Re-run to update. Idempotent -- deletes and re-creates if already exists.
  Battery flags cleared (see rules/windows-pitfalls.md -- 0x800710E0 gate).
#>

$ErrorActionPreference = 'Stop'

$TaskName   = 'Jarvis-EngineWatchdog'
$JarvisDir  = 'C:\Users\mattm\ThinkorSwim\jarvis-trader'
$Script     = "$JarvisDir\scripts\engine-watchdog.ps1"
$PwshExe    = "$env:LOCALAPPDATA\Microsoft\WindowsApps\pwsh.exe"

if (-not (Test-Path $PwshExe)) {
    $PwshExe = (Get-Command pwsh -ErrorAction Stop).Source
}

$action  = New-ScheduledTaskAction -Execute $PwshExe `
               -Argument "-NonInteractive -NoProfile -File `"$Script`"" `
               -WorkingDirectory $JarvisDir

$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 5) `
               -Once -At (Get-Date)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 8) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable

# Remove existing task if present
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action   $action `
    -Trigger  $trigger `
    -Settings $settings `
    -RunLevel Limited `
    -Force | Out-Null

Write-Host "Installed: $TaskName (every 5 min, battery-gated cleared)"
Write-Host "Verify:    schtasks /Query /TN `"$TaskName`" /V /FO LIST"
Write-Host "Test now:  Start-ScheduledTask -TaskName `"$TaskName`""
