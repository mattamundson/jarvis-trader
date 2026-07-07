#requires -Version 5.1
# Hermes Upgrade Scanner -- nightly Phase 1+2 of the Hermes self-improvement loop.
#
# Scans the channel-1490851279180660819 deep_analyzer corpus for Hermes-applicable
# bookmarks, classifies each via Haiku 4.5, writes a tiered backlog to
# C:\Users\mattm\.hermes\upgrade\backlog.md + .jsonl. Preserves apply_status
# on rerun (default merge mode).
#
# Schedule: daily 05:00 CT via Jarvis-HermesUpgradeScan task.
# Exit codes:
#   0 -- backlog written
#   1 -- pipeline failure (engine venv missing, python error, etc.)
#   2 -- no candidates surfaced (treated as informational, not failure)
$ErrorActionPreference = "Stop"
# Force UTF-8 so prints of entry titles containing -> (U+2192) don't crash
# the daily cron run on Windows cp1252 stdout.
$env:PYTHONIOENCODING = "utf-8"
Start-Transcript -Path "$env:TEMP\hermes_upgrade_scan.log" -Append

$repo   = "C:\Users\mattm\ThinkorSwim\jarvis-trader"
$python = "$repo\engine\.venv\Scripts\python.exe"
$db     = "$repo\engine\data\jarvis_trader.db"

if (-not (Test-Path $python)) {
    Write-Host "ERROR: engine venv python missing at $python"
    Stop-Transcript
    exit 1
}
if (-not (Test-Path $db)) {
    Write-Host "ERROR: jarvis_trader.db missing at $db"
    Stop-Transcript
    exit 1
}

Push-Location "$repo\engine"
try {
    & $python -m discord.hermes_upgrade `
        --db data/jarvis_trader.db `
        --channel-id 1490851279180660819 `
        --min-score 0.25 `
        --concurrency 5
    $rc = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($rc -ne 0) {
    Write-Host "ERROR: hermes_upgrade pipeline exited $rc"
    Stop-Transcript
    exit 1
}

# Report the produced backlog
$backlog = "$env:USERPROFILE\.hermes\upgrade\backlog.md"
if (Test-Path $backlog) {
    $size = (Get-Item $backlog).Length
    Write-Host "backlog.md size: $size bytes"
    Get-Content $backlog -TotalCount 3 | ForEach-Object { Write-Host "  $_" }
} else {
    Write-Host "WARN: backlog.md not produced at $backlog"
}

Stop-Transcript
exit 0
