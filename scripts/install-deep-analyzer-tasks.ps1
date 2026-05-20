#requires -Version 5.1
$ErrorActionPreference = "Stop"

$repo = "C:\Users\mattm\ThinkorSwim\jarvis-trader"
$pwsh = "$env:LOCALAPPDATA\Microsoft\WindowsApps\pwsh.exe"

# --- Task 1: 2-minute loop ---
$loopName = "JarvisTrader_DiscordDeepAnalyzer"
$loopAction = New-ScheduledTaskAction -Execute $pwsh `
    -Argument "-NoProfile -File `"$repo\scripts\deep_analyzer_loop.ps1`""
$loopTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 2)
$loopSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 1 -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $loopName -Action $loopAction `
    -Trigger $loopTrigger -Settings $loopSettings -Force -RunLevel Limited

Write-Host "Installed: $loopName (every 2 min)"

# --- Task 2: 06:00 daily digest ---
$digestName = "JarvisTrader_DiscordDigest"
$digestAction = New-ScheduledTaskAction -Execute $pwsh `
    -Argument "-NoProfile -File `"$repo\scripts\deep_analyzer_digest.ps1`""
$digestTrigger = New-ScheduledTaskTrigger -Daily -At "06:00"
$digestSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

Register-ScheduledTask -TaskName $digestName -Action $digestAction `
    -Trigger $digestTrigger -Settings $digestSettings -Force -RunLevel Limited

Write-Host "Installed: $digestName (daily 06:00)"

# --- Verify ---
schtasks /Query /TN $loopName /V /FO LIST | Select-String "Status|Next Run"
schtasks /Query /TN $digestName /V /FO LIST | Select-String "Status|Next Run"
