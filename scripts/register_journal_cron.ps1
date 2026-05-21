#Requires -Version 5.1
<#
.SYNOPSIS
    Register the Jarvis-TradingJournal-Daily scheduled task.

.DESCRIPTION
    Idempotent registration of a Windows Scheduled Task that runs
    generate_trading_journal.py at 5:00 PM CT every weekday (Mon-Fri).

    The task is OFF by default — it must be manually enabled or this script
    run to activate it (the JARVIS trading journal cron flag).

    Re-running this script is safe; it skips registration if the task already
    exists and prints its current state.

.PARAMETER Force
    If specified, deletes and re-creates the task even if it already exists.
    Use this to update the trigger time or script path.

.PARAMETER DryRun
    Print the proposed schtasks command without executing it.

.EXAMPLE
    engine\.venv\Scripts\python scripts\generate_trading_journal.py --dry-run
    .\scripts\register_journal_cron.ps1
    .\scripts\register_journal_cron.ps1 -Force
    .\scripts\register_journal_cron.ps1 -DryRun
#>

param(
    [switch]$Force,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

$TaskName   = "Jarvis-TradingJournal-Daily"
# 5:00 PM Central Time = 23:00 UTC (CST, UTC-6) / 22:00 UTC (CDT, UTC-5).
# Scheduled at 23:00 UTC to cover CST (winter); CDT (summer) means it runs at 6 PM CT.
# Adjust here if you want strict CDT-aware scheduling.
$TriggerTime = "23:00"  # UTC — effectively 5pm CST / 6pm CDT

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PythonExe   = Join-Path $ProjectRoot "engine\.venv\Scripts\python.exe"
$ScriptPath  = Join-Path $ProjectRoot "scripts\generate_trading_journal.py"

# Use WindowsApps pwsh shim for the wrapper — survives Store auto-updates.
# The actual task action is python.exe directly (not a shell wrapper).

$TaskAction  = "`"$PythonExe`" `"$ScriptPath`""

# ---------------------------------------------------------------------------
# Validate prerequisites
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "=== Jarvis-TradingJournal-Daily Cron Registration ==="
Write-Host "Task name:    $TaskName"
Write-Host "Trigger time: $TriggerTime (UTC, weekdays Mon-Fri)"
Write-Host "Python:       $PythonExe"
Write-Host "Script:       $ScriptPath"
Write-Host ""

if (-not (Test-Path $PythonExe)) {
    Write-Error "Python venv not found: $PythonExe`nRun: repair-engine-venv.ps1"
    exit 1
}
if (-not (Test-Path $ScriptPath)) {
    Write-Error "Journal script not found: $ScriptPath"
    exit 1
}

# ---------------------------------------------------------------------------
# Check if already registered
# ---------------------------------------------------------------------------

$existing = $null
try {
    $existing = schtasks /Query /TN $TaskName /FO LIST 2>&1
    $taskExists = $LASTEXITCODE -eq 0
} catch {
    $taskExists = $false
}

if ($taskExists -and (-not $Force)) {
    Write-Host "Task '$TaskName' already exists. Use -Force to re-register."
    Write-Host ""
    schtasks /Query /TN $TaskName /V /FO LIST 2>&1 | Select-String -Pattern "Status|Next Run|Last Run|Run As"
    Write-Host ""
    Write-Host "To delete: schtasks /Delete /TN `"$TaskName`" /F"
    Write-Host "To enable cron: this task is already registered (runs daily at $TriggerTime UTC Mon-Fri)."
    exit 0
}

# ---------------------------------------------------------------------------
# Delete existing if --Force
# ---------------------------------------------------------------------------

if ($taskExists -and $Force) {
    Write-Host "Deleting existing task ($TaskName) per -Force..."
    if (-not $DryRun) {
        schtasks /Delete /TN $TaskName /F
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to delete existing task."
            exit 1
        }
    } else {
        Write-Host "  [DRY RUN] Would execute: schtasks /Delete /TN `"$TaskName`" /F"
    }
}

# ---------------------------------------------------------------------------
# Register the task
# ---------------------------------------------------------------------------
# schtasks.exe is used directly (not Register-ScheduledTask) because:
# 1. New-ScheduledTaskTrigger -Weekly -DaysOfWeek can fail on Win 11 26200
#    with HRESULT 0x80070057 (see rules/windows-pitfalls.md).
# 2. schtasks /SC WEEKLY /D is reliable across all Win 11 builds.
#
# Schedule: WEEKLY, MON through FRI, starting at $TriggerTime.
# Note: schtasks does not have a MON-FRI shorthand; register 5 separate
# day flags via a single /D "MON,TUE,WED,THU,FRI" value.
# ---------------------------------------------------------------------------

$cmd = @(
    "schtasks", "/Create",
    "/TN", "`"$TaskName`"",
    "/TR", "`"$TaskAction`"",
    "/SC", "WEEKLY",
    "/D", "MON,TUE,WED,THU,FRI",
    "/ST", $TriggerTime,
    "/RL", "LIMITED",
    "/F"   # overwrite if already exists (safety for -Force path)
)
$cmdStr = $cmd -join " "

Write-Host "Registering scheduled task..."
Write-Host "  Command: $cmdStr"
Write-Host ""

if ($DryRun) {
    Write-Host "[DRY RUN] Would execute: $cmdStr"
    Write-Host ""
    Write-Host "=== DRY RUN COMPLETE — no task registered ==="
    exit 0
}

Invoke-Expression $cmdStr
if ($LASTEXITCODE -ne 0) {
    Write-Error "schtasks registration failed (exit $LASTEXITCODE)."
    exit 1
}

# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "=== Verification ==="
schtasks /Query /TN $TaskName /V /FO LIST 2>&1 | Select-String -Pattern "Status|Next Run|Run As|Task To Run"
Write-Host ""
Write-Host "Task registered successfully."
Write-Host ""
Write-Host "To disable (without deleting):  schtasks /Change /TN `"$TaskName`" /Disable"
Write-Host "To re-enable:                   schtasks /Change /TN `"$TaskName`" /Enable"
Write-Host "To delete permanently:          schtasks /Delete /TN `"$TaskName`" /F"
Write-Host ""
Write-Host "See docs/runbooks/TRADING_JOURNAL_RUNBOOK.md for full operational guidance."
