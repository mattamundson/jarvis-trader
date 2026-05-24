# install-wfo-refresh-task.ps1 — Register "JARVIS-WFO-Refresh" scheduled task.
#
# Runs wfo-refresh.ps1 on the 1st of each month at 07:00 local time to
# re-evaluate MES rank11 and MGC rank4 walk-forward verdicts.  A FAIL
# verdict in either instrument means the production signal should be halted
# pending investigation.
#
# Idempotent: unregisters any existing task of the same name before re-creating.
# No admin required — runs under the current interactive user account.
#
# Usage:
#   pwsh -NoProfile -File scripts/install-wfo-refresh-task.ps1
#
# Verify after registration:
#   schtasks /Query /TN "JARVIS-WFO-Refresh" /FO LIST
#
# Dry-run:
#   Start-ScheduledTask -TaskName "JARVIS-WFO-Refresh"
#   Get-ScheduledTaskInfo -TaskName "JARVIS-WFO-Refresh" | Format-List LastRunTime, LastTaskResult

$ErrorActionPreference = "Stop"

$taskName = "JARVIS-WFO-Refresh"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$psScript = Join-Path $repoRoot "scripts\wfo-refresh.ps1"
$pwsh     = (Get-Command pwsh -ErrorAction SilentlyContinue)?.Source
if (-not $pwsh) { $pwsh = "%LOCALAPPDATA%\Microsoft\WindowsApps\pwsh.exe" }

if (-not (Test-Path $psScript)) {
    Write-Error "wfo-refresh.ps1 not found at $psScript"
    exit 1
}

Write-Host "Registering task: $taskName"
Write-Host "  Script : $psScript"
Write-Host "  Trigger: 1st of each month at 07:00 local time"
Write-Host ""

# Remove prior registration (idempotent)
try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
} catch {}

$action = New-ScheduledTaskAction `
    -Execute $pwsh `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$psScript`"" `
    -WorkingDirectory $repoRoot

# Win 11 26200 note: New-ScheduledTaskTrigger -Monthly can throw HRESULT 0x80070057.
# Fall back to schtasks.exe if the PowerShell cmdlet fails.
$taskRegistered = $false
try {
    $trigger = New-ScheduledTaskTrigger -Monthly -DaysOfMonth 1 -At "07:00AM"

    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
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
        -Description "Monthly WFO re-run for MES rank11 and MGC rank4. Detects regime drift before it affects live P&L. FAIL verdict = halt signal and investigate." `
        | Out-Null

    $taskRegistered = $true
    Write-Host "Registered via New-ScheduledTaskTrigger (PowerShell path)."
} catch {
    Write-Host "PowerShell monthly trigger failed ($($_.Exception.Message)) — falling back to schtasks.exe"
}

if (-not $taskRegistered) {
    # schtasks.exe fallback for HRESULT 0x80070057 (Win 11 26200 bug)
    $cmd = "pwsh -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$psScript`""
    schtasks.exe /Create /SC MONTHLY /D 1 /MO 1 /TN $taskName /TR $cmd /ST "07:00" /RL LIMITED /F
    if ($LASTEXITCODE -ne 0) {
        Write-Error "schtasks.exe fallback also failed. Register the task manually."
        exit 1
    }
    Write-Host "Registered via schtasks.exe fallback."
}

Write-Host ""
Write-Host "Registered: $taskName"
Write-Host ""
Write-Host "Verify:"
Write-Host "  schtasks /Query /TN `"$taskName`" /FO LIST"
Write-Host ""
Write-Host "Dry-run:"
Write-Host "  Start-ScheduledTask -TaskName `"$taskName`""
Write-Host "  Get-ScheduledTaskInfo -TaskName `"$taskName`" | Format-List LastRunTime, LastTaskResult"
