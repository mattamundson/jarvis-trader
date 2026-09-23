# discord_weekly_export.ps1 — DAILY DCE export into C:\Users\mattm\discord-export\
# (file still named *_weekly_* historically; task name updated to *Daily*.)
#
# Scheduled via Windows Task Scheduler (task name: JarvisDiscordDailyExport).
# Triggers every day 05:30 local CT (30 min before engine/main.py:1483-1527
# Mon-Fri 06:00 CT importer runs, avoiding export/import race).
#
# Import is NOT done here — engine's existing Mon-Fri scheduler handles it
# automatically. Weekend exports land on Mon AM import.
#
# Minimum viable channel set (expand `$Channels` array below to cover more):
#   * #general          (741484321142997086) — Corey commentary, feeds corey_session_bias
#   * indicator-alerts  (1133508659993915492) — signal overlay data
#
# Design notes (see docs/incident-notes/2026-04-17-t2.1-discord-staleness.md):
<<<<<<< HEAD
#   * Token read from .token file on each run — never embedded in script or logs
=======
#   * Token read from process DISCORD_TOKEN first, then engine\.env, then
#     C:\Users\mattm\discord-export\.token fallback. Never embedded in scripts/logs and never passed via
#     DCE --token/-t argv; DCE reads DISCORD_TOKEN from the process environment.
#   * If DCE reports "Authentication token is invalid", rotate the token before
#     rerunning; stale futures_sentiment is a credential-freshness blocker.
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
#   * `--after` rolling 3-day window; parser.py:55 handles "(after YYYY-MM-DD)"
#     filenames; storage.py INSERT OR IGNORE on message_id dedupes overlap
#   * Exits non-zero on any failure so Task Scheduler reports "Last Run Result != 0"

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'   # suppress DCE's in-band progress bar in log

# ── Paths ─────────────────────────────────────────────────────────────────────
$Dce       = 'C:\Users\mattm\tools\DiscordChatExporter.Cli\DiscordChatExporter.Cli.exe'
$Exports   = Join-Path $env:USERPROFILE 'discord-export'
$TokenFile = Join-Path $Exports '.token'
$EngineDir = 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine'
$LogDir    = Join-Path $EngineDir 'logs'
$LogFile   = Join-Path $LogDir 'discord_weekly_export.log'

# ── Channel subset — edit to include/exclude ─────────────────────────────────
$Channels = @(
    # Corey Auction Tools User Room — agent-critical signals
    @{ Name = 'corey-general';         Id = '741484321142997086'  }   # Corey commentary, feeds corey_session_bias
    @{ Name = 'corey-indicator-alerts';Id = '1133508659993915492' }   # Auction-Tools indicator overlay

    # Jarvis-Trader — Matt's personal research/bookmark dump (X links, GitHub, etc.)
    # No engine consumer yet; future bookmark-ingestion feature will read from this.
    @{ Name = 'jarvis-trader-general'; Id = '1490851279180660819' }

    # Uncomment to widen coverage if bot_signals staleness becomes an issue:
    # @{ Name = 'bot-alerts-MCL';   Id = '...' }
    # @{ Name = 'bot-alerts-MNQ';   Id = '...' }
)

# ── Helpers ──────────────────────────────────────────────────────────────────
function Write-Log {
    param([string]$Level, [string]$Msg)
    $ts = Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz'
    $line = "$ts [$Level] $Msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

# ── Pre-flight ───────────────────────────────────────────────────────────────
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
Write-Log 'INFO' "=== weekly export start ==="

if (-not (Test-Path $Dce))       { Write-Log 'ERROR' "DCE not found at $Dce"; exit 2 }
<<<<<<< HEAD
if (-not (Test-Path $TokenFile)) { Write-Log 'ERROR' "Token file missing at $TokenFile"; exit 3 }

$Token = (Get-Content $TokenFile -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($Token)) { Write-Log 'ERROR' 'Token file empty'; exit 5 }
=======
$Token = $null
$TokenSource = $null
$EngineEnv = Join-Path $EngineDir '.env'
if (-not [string]::IsNullOrWhiteSpace($env:DISCORD_TOKEN)) {
    $Token = $env:DISCORD_TOKEN.Trim()
    $TokenSource = 'process_env'
}
if ([string]::IsNullOrWhiteSpace($Token) -and (Test-Path $EngineEnv)) {
    $line = Get-Content $EngineEnv | Where-Object { $_ -match '^DISCORD_TOKEN=' } | Select-Object -First 1
    if ($line) {
        $Token = ($line -replace '^DISCORD_TOKEN=', '').Trim().Trim('"').Trim("'")
        $TokenSource = 'engine_env'
    }
}
if ([string]::IsNullOrWhiteSpace($Token) -and (Test-Path $TokenFile)) {
    $Token = (Get-Content $TokenFile -Raw).Trim()
    $TokenSource = 'token_file'
}
if ([string]::IsNullOrWhiteSpace($Token)) { Write-Log 'ERROR' "Discord token missing: neither $TokenFile nor engine\.env DISCORD_TOKEN is populated"; exit 3 }
Write-Log 'INFO' "Discord token source: $TokenSource"
$env:DISCORD_TOKEN = $Token
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2

# ── Export each channel (incremental: last 3 days, daily overlap) ────────────
# Full re-export of #general is 60k+ messages and rate-limits to ~12hr wall.
# Daily `--after 3d` keeps each run <1 MB. Parser handles the
# `(after YYYY-MM-DD)` filename suffix (parser.py:55); importer uses
# INSERT OR IGNORE on message_id (storage.py:96,139,176,201) → dedup is free.
# 3-day window > daily gap means a single missed run still gets covered next day.
$After  = (Get-Date).AddDays(-3).ToString('yyyy-MM-dd')
$failed = @()
foreach ($ch in $Channels) {
    Write-Log 'INFO' "Exporting channel $($ch.Name) ($($ch.Id)) after $After"
    try {
<<<<<<< HEAD
        & $Dce export -c $ch.Id -t $Token -o "$Exports\" -f Json --after $After --respect-rate-limits 2>&1 |
            ForEach-Object { Write-Log 'DCE' $_ }
        if ($LASTEXITCODE -ne 0) { throw "DCE exit $LASTEXITCODE" }
        Write-Log 'INFO' "Export OK: $($ch.Name)"
    } catch {
        Write-Log 'ERROR' "Export failed for $($ch.Name): $_"
=======
        $output = & $Dce export -c $ch.Id -o "$Exports\" -f Json --after $After --respect-rate-limits 2>&1
        $output | ForEach-Object { Write-Log 'DCE' $_ }
        if ($LASTEXITCODE -ne 0) { throw "DCE exit $LASTEXITCODE" }
        Write-Log 'INFO' "Export OK: $($ch.Name)"
    } catch {
        $invalidToken = $false
        try { $invalidToken = (($output -join "`n") -match 'Authentication token is invalid') } catch {}
        if ($invalidToken) {
            Write-Log 'ERROR' "Export failed for $($ch.Name): invalid Discord token blocks futures_sentiment freshness — rotate DISCORD_TOKEN and rerun exporter"
        } else {
            Write-Log 'ERROR' "Export failed for $($ch.Name): $_"
        }
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
        $failed += $ch.Name
    }
}

if ($failed.Count -gt 0) {
    Write-Log 'ERROR' "Channels failed: $($failed -join ', ')"
    exit 10
}

# Import is handled by the engine's existing Mon–Fri 06:00 CT scheduler
# (engine/main.py:1483-1527 → run_discord_import). Keeping the wrapper
# export-only avoids PowerShell/Python stderr-interop fragility under
# $ErrorActionPreference='Stop' and makes each run a single atomic concern.
Write-Log 'INFO' '=== weekly export complete (import deferred to Mon AM engine scheduler) ==='
exit 0
