# install-dce-nightly-task.ps1 — Register Windows Task Scheduler task
# "JARVIS-DCE-Nightly" to run dce-nightly.ps1 daily at 05:15 CT.
#
# Runs the export before morning-brief (engine/ecosystem.config.js jarvis-morning-brief
# fires at 06:30 CT) so agents always get fresh Corey data at brief time.
#
<<<<<<< HEAD
=======
# Token safety: dce-nightly.ps1 passes Discord credentials only through the
# DISCORD_TOKEN process environment, never DCE --token/-t command-line args.
# If the task reports "Authentication token is invalid", rotate the token and
# rerun; the expected blocker is credential freshness, not the ETL parser.
#
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
# Idempotent: deletes any prior registration with the same task name before
# re-creating. Safe to re-run after changes to the script or schedule.
#
# No admin required — runs under the current interactive user account.
#
# Usage:
#   pwsh -NoProfile -File scripts/install-dce-nightly-task.ps1
#
# Verify after registration:
#   schtasks /Query /TN "JARVIS-DCE-Nightly" /FO LIST

$ErrorActionPreference = "Stop"

$taskName  = "JARVIS-DCE-Nightly"
$repoRoot  = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
$psScript  = Join-Path $repoRoot "scripts\dce-nightly.ps1"
$pwsh      = (Get-Command pwsh -ErrorAction SilentlyContinue)?.Source
if (-not $pwsh) { $pwsh = "pwsh" }   # rely on PATH if not found via Get-Command

# ── Pre-flight ─────────────────────────────────────────────────────────────────
if (-not (Test-Path $psScript)) {
    Write-Host "ERROR: dce-nightly.ps1 not found at $psScript"
    exit 1
}

Write-Host "Registering task: $taskName"
Write-Host "  Script : $psScript"
Write-Host "  Trigger: daily 05:15 CT (machine local time — adjust if machine TZ != CT)"
Write-Host ""

# ── Remove prior registration (idempotent) ─────────────────────────────────────
try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
} catch {}

# ── Build task components ──────────────────────────────────────────────────────
# PowerShell arguments: -NoProfile so user profile doesn't interfere;
# -NonInteractive so the script can run headless; -File to exec the script.
$action = New-ScheduledTaskAction `
    -Execute $pwsh `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$psScript`"" `
    -WorkingDirectory $repoRoot

# 05:15 local machine time. If machine timezone is CT this is 05:15 CT.
# Task Scheduler uses local time; PM2 cron uses TZ=America/Chicago.
$trigger = New-ScheduledTaskTrigger -Daily -At "05:15AM"

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
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
    -Description "Nightly DiscordChatExporter refresh for Corey #market-updates + #general. Ingest into SQLite + sentiment ETL. Alert via WhatsApp if 2 consecutive days fail." `
    | Out-Null

Write-Host "Registered: $taskName"
Write-Host ""
Write-Host "Verify:"
Write-Host "  schtasks /Query /TN `"$taskName`" /FO LIST"
Write-Host ""
Write-Host "Dry-run now (optional):"
Write-Host "  Start-ScheduledTask -TaskName `"$taskName`""
Write-Host "  Get-ScheduledTaskInfo -TaskName `"$taskName`" | Format-List LastRunTime, LastTaskResult"
Write-Host ""
Write-Host "Note: If machine timezone is not CT, adjust trigger time so the task runs at"
Write-Host "  05:15 CT (before jarvis-morning-brief at 06:30 CT)."
