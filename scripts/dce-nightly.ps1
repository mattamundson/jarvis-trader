# dce-nightly.ps1 — Nightly DCE export for #market-updates + ingest chain.
#
# 1. Exports Corey's #market-updates and #general for the last 48 hours via
#    DiscordChatExporter CLI, writing JSON to C:\Users\mattm\discord-export\.
# 2. Chains into engine/scripts/nightly_discord_export.py which ingests the
#    fresh JSON into SQLite and runs the sentiment ETL (--no-ingest flag skips).
# 3. Tracks consecutive-failure days in engine/logs/dce_failure_streak.txt.
#    On day 2+ of failures, fires a WhatsApp alert via notify_corey_stale.
#
# Registered as Windows Task Scheduler task "JARVIS-DCE-Nightly" at 05:15 CT.
# See scripts/install-dce-nightly-task.ps1 for one-time registration.
#
# Auth token: read from C:\Users\mattm\discord-export\.token (one line, no quotes).
# Never echo the token; never embed it in this script.
#
# Exit codes:
#   0  — success (all exports + ingest ok)
#   2  — DCE binary not found
#   3  — token file missing or empty
#   10 — one or more channel exports failed
#   20 — ingest/ETL failed

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

# ── Paths ──────────────────────────────────────────────────────────────────────
$Dce          = if ($env:DCE_CLI_PATH) { $env:DCE_CLI_PATH } else { 'C:\Users\mattm\tools\DiscordChatExporter.Cli\DiscordChatExporter.Cli.exe' }
$ExportsRoot  = Join-Path $env:USERPROFILE 'discord-export'
$TokenFile    = Join-Path $ExportsRoot '.token'
$EngineDir    = Join-Path $PSScriptRoot '..\engine'
$EngineDir    = (Resolve-Path $EngineDir).Path
$Python       = Join-Path $EngineDir '.venv\Scripts\python.exe'
$LogDir       = Join-Path $EngineDir 'logs'
$LogFile      = Join-Path $LogDir 'dce_nightly.log'
$StreakFile   = Join-Path $LogDir 'dce_failure_streak.txt'

# ── Channels to export (only those that feed agent decisions) ──────────────────
# #general feeds corey_session_bias; #market-updates feeds discord_corey_commentary.
$Channels = @(
    @{ Name = 'market-updates'; Id = '806343100435660801' }
    @{ Name = 'general';        Id = '741484321142997086' }
)

# Rolling window: 48h covers a missed run without a full re-download.
# parser.py:55 handles "(after YYYY-MM-DD)" filename suffixes.
# storage.py INSERT OR IGNORE on message_id dedupes overlap for free.
$LookbackDays = 2

# ── Helpers ───────────────────────────────────────────────────────────────────
function Write-Log {
    param([string]$Level, [string]$Msg)
    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
    $ts   = Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz'
    $line = "$ts [$Level] $Msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Get-FailureStreak {
    if (Test-Path $StreakFile) {
        try { return [int](Get-Content $StreakFile -Raw).Trim() } catch { return 0 }
    }
    return 0
}

function Set-FailureStreak([int]$Count) {
    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
    Set-Content -Path $StreakFile -Value "$Count" -Encoding UTF8
}

# ── Pre-flight ────────────────────────────────────────────────────────────────
Write-Log 'INFO' "=== dce-nightly start ==="

if (-not (Test-Path $Dce)) {
    Write-Log 'ERROR' "DCE not found at $Dce — set DCE_CLI_PATH env var or install to default path"
    exit 2
}
if (-not (Test-Path $TokenFile)) {
    Write-Log 'ERROR' "Token file missing: $TokenFile — create it with your Discord user token (one line, no quotes)"
    exit 3
}
$Token = (Get-Content $TokenFile -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($Token)) {
    Write-Log 'ERROR' "Token file is empty: $TokenFile"
    exit 3
}

# ── Export each channel ────────────────────────────────────────────────────────
$After  = (Get-Date).AddDays(-$LookbackDays).ToString('yyyy-MM-dd')
$failed = @()

foreach ($ch in $Channels) {
    Write-Log 'INFO' "Exporting $($ch.Name) ($($ch.Id)) after $After"
    try {
        # Never log the token — pass via positional arg, redact in logs.
        $output = & $Dce export -c $ch.Id -t $Token -o "$ExportsRoot\" -f Json --after $After --respect-rate-limits 2>&1
        $output | ForEach-Object { Write-Log 'DCE' "$_" }
        if ($LASTEXITCODE -ne 0) { throw "DCE exited $LASTEXITCODE" }
        Write-Log 'INFO' "Export OK: $($ch.Name)"
    } catch {
        Write-Log 'ERROR' "Export failed for $($ch.Name): $_"
        $failed += $ch.Name
    }
}

if ($failed.Count -gt 0) {
    Write-Log 'ERROR' "Channel exports failed: $($failed -join ', ')"

    # ── Consecutive-failure tracking + WhatsApp alert ─────────────────────────
    $streak = (Get-FailureStreak) + 1
    Set-FailureStreak $streak
    Write-Log 'WARN' "Failure streak now $streak day(s)"

    if ($streak -ge 2) {
        Write-Log 'WARN' "Streak >= 2 — firing WhatsApp alert via notify_corey_stale"
        if (Test-Path $Python) {
            try {
                & $Python -c @"
import sys, asyncio
sys.path.insert(0, r'$EngineDir')
from notifications.openclaw_notifier import notify_corey_stale
asyncio.run(notify_corey_stale(days_stale=$streak, last_message_date='unknown — DCE export failed'))
"@ 2>&1 | ForEach-Object { Write-Log 'ALERT' "$_" }
            } catch {
                Write-Log 'ERROR' "WhatsApp alert dispatch failed: $_"
            }
        } else {
            Write-Log 'WARN' "Python venv not found at $Python — skipping WhatsApp alert"
        }
    }

    exit 10
}

# ── Reset failure streak on clean export ─────────────────────────────────────
Set-FailureStreak 0

# ── Chain ingest + ETL ────────────────────────────────────────────────────────
Write-Log 'INFO' "Chaining nightly_discord_export.py for ingest + sentiment ETL"
if (-not (Test-Path $Python)) {
    Write-Log 'ERROR' "Python venv not found at $Python — skipping ingest"
    exit 20
}

try {
    # nightly_discord.py imports the fresh JSON from $ExportsRoot into SQLite,
    # then runs the sentiment ETL. It is the ingest-only companion that reads
    # whatever JSON is on disk — no re-export.
    # Must run with cwd=$EngineDir so `scripts.nightly_discord` resolves.
    Push-Location $EngineDir
    try {
        $ingestOut = & $Python -m scripts.nightly_discord 2>&1
        $ingestOut | ForEach-Object { Write-Log 'ETL' "$_" }
        if ($LASTEXITCODE -ne 0) { throw "nightly_discord exited $LASTEXITCODE" }
        Write-Log 'INFO' "Ingest + ETL complete"
    } finally {
        Pop-Location
    }
} catch {
    Write-Log 'ERROR' "Ingest/ETL failed: $_"
    exit 20
}

Write-Log 'INFO' "=== dce-nightly complete ==="
exit 0
