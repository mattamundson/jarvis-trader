#Requires -Version 5.1
<#
.SYNOPSIS
  Watchdog for jarvis-engine: detects event-loop saturation and auto-restarts.

.DESCRIPTION
  Hits /health with a 10-second timeout. If the engine is unresponsive, kills
  the process holding port 8010 and calls restart_engine.ps1 to bring it back
  under PM2 management.

  Designed to run every 5 minutes via Task Scheduler (Jarvis-EngineWatchdog).
  One instance at a time -- the task is configured with ExecutionTimeLimit=8min
  so a stuck watchdog doesn't pile up.

.PARAMETER DryRun
  Print what would happen without killing or restarting anything.
#>
param([switch]$DryRun)

$ErrorActionPreference = 'Continue'

$EngineUrl = 'http://127.0.0.1:8010/health'
$Port = 8010
$JarvisDir = 'C:\Users\mattm\ThinkorSwim\jarvis-trader'
$LogDir = "$JarvisDir\logs"
$LogFile = "$LogDir\engine-watchdog.log"
$MaxLogKB = 512

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

function Write-Log([string]$msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Write-Host $line
    try { Add-Content -Path $LogFile -Value $line -Encoding UTF8 } catch {}
}

function Trim-Log {
    try {
        $kb = (Get-Item $LogFile -ErrorAction Stop).Length / 1KB
        if ($kb -gt $MaxLogKB) {
            $lines = Get-Content $LogFile
            $lines | Select-Object -Last 400 | Set-Content $LogFile -Encoding UTF8
        }
    }
    catch {}
}

# Check health.
#
# IMPORTANT: a SINGLE failed probe is NOT sufficient to declare the engine dead.
# The engine's async event loop saturates for several seconds at a time during
# heavy pipeline bursts (scanner pass, LLM debate, IB reconciliation) and a
# normal /health can momentarily exceed a short timeout while the process is
# perfectly alive and working. A single-probe watchdog interprets that spike as
# "dead" and restarts mid-work -- which, when several restarts stack up, races
# multiple engine instances onto the cost-tracker SQLite DB and produces a
# "database is locked" startup crash-loop (forensic: 2026-06-05 incident).
#
# So: require THREE consecutive failures, each with a generous timeout, spaced a
# few seconds apart (~45-75s of *sustained* unresponsiveness) before acting.
# Transient saturation recovers within one or two probes; a genuine hang fails
# all three. One success at any point clears the alarm.
$ProbeTimeoutSec = 15
$ProbeCount = 3
$ProbeGapSec = 8
$healthy = $false
for ($probe = 1; $probe -le $ProbeCount; $probe++) {
    try {
        $resp = Invoke-WebRequest -Uri $EngineUrl -TimeoutSec $ProbeTimeoutSec -UseBasicParsing -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    }
    catch {}
    if ($probe -lt $ProbeCount) { Start-Sleep -Seconds $ProbeGapSec }
}

if ($healthy) {
    # Silent on success -- log would fill up every 5 min
    exit 0
}

Write-Log "FAIL: /health unresponsive after $ProbeCount consecutive probes (${ProbeTimeoutSec}s each) -- checking port $Port"


# --- Log-recency guard (2026-06-18, Amo-authorized) ------------------------
# /health can stay unresponsive for >1min during RTH-open pipeline saturation
# while the engine event loop is perfectly alive and working. Before the
# disruptive kill+restart, confirm the engine is genuinely dead via log
# freshness: a line written in the last 60s means the loop is running
# (apscheduler jobs, IBKR bars, TVStreamer reads), so a slow /health is
# saturation, not death -- skip the restart. A truly hung loop stops logging,
# so a stale log still restarts. Stat failure falls through to restart
# (fail-safe, preserves prior behavior).
# Candidate engine logs, freshest wins. The guard used to stat ONE hard-coded
# path -- $env:USERPROFILE\.pm2\logs\jarvis-engine-error.log -- which DOES NOT
# EXIST on this host (verified 2026-09-19: C:\Users\<user>\.pm2\logs contains
# only jarvis-dashboard-*.log and pm2-logrotate-*.log; the engine writes to
# engine/logs/). Get-Item therefore threw on every tick, the catch fell
# through, and the guard was INERT: every /health saturation produced an
# unconditional restart decision -- a restart-storm contributor.
$EngineLogCandidates = @(
    (Join-Path $PSScriptRoot "..\engine\logs\jarvis.log"),            # live app log (structured JSON)
    (Join-Path $PSScriptRoot "..\engine\logs\engine-boot-error.log"), # live app log (text)
    "$env:USERPROFILE\.pm2\logs\jarvis-engine-error.log"              # legacy PM2 path (absent here)
)
$EngineLog = $null
$logAgeSec = $null
foreach ($candidate in $EngineLogCandidates) {
    try {
        $item = Get-Item $candidate -ErrorAction Stop
        $age = ((Get-Date) - $item.LastWriteTime).TotalSeconds
        if ($null -eq $logAgeSec -or $age -lt $logAgeSec) {
            $logAgeSec = $age
            $EngineLog = $candidate
        }
    }
    catch {}
}

if ($null -eq $logAgeSec) {
    # No candidate exists at all: preserve prior fail-safe behaviour (restart).
    Write-Log ("WARN: no engine log candidate exists ({0}) -- falling through to restart on /health failure" -f ($EngineLogCandidates -join '; '))
}
elseif ($logAgeSec -lt 60) {
    Write-Log ("SKIP: /health failed {1}x but engine log fresh ({0:N0}s, {2}) -- event loop alive, not restarting (RTH saturation)" -f $logAgeSec, $ProbeCount, $EngineLog)
    Trim-Log
    exit 0
}
else {
    Write-Log ("CONFIRM-DEAD: engine log stale ({0:N0}s, {2}) AND /health failed {1}x -- genuine hang, restarting" -f $logAgeSec, $ProbeCount, $EngineLog)
}
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Cross-watchdog restart lock. This script and check-engine-health.ps1
# (~/scripts/, hourly cadence) can both decide independently that the engine
# needs a restart -- with no awareness of each other, each one's force-kill +
# restart_engine.ps1 call can land while the OTHER's restart is still binding
# to port 8010, producing an orphan-kill collision chain (204+ restarts/day
# observed 2026-07-09, see engine/logs/port_guardian_restarts.jsonl). This
# lock makes whichever watchdog fires first own the restart; the other skips
# rather than force-killing a process that's mid-boot from a restart already
# in flight. TTL-based (no explicit release) so a crashed watchdog can't wedge
# the lock permanently -- 120s comfortably covers kill + restart_engine.ps1 +
# PM2 rebind, well under this script's own 5-min cadence.
$RestartLockFile = Join-Path $env:TEMP 'jarvis-engine-restart.lock'
$RestartLockTTL = 120  # seconds

if (Test-Path $RestartLockFile) {
    try {
        $lockAgeSec = ((Get-Date) - (Get-Item $RestartLockFile).LastWriteTime).TotalSeconds
        if ($lockAgeSec -lt $RestartLockTTL) {
            $lockOwner = Get-Content $RestartLockFile -Raw -ErrorAction SilentlyContinue
            Write-Log ("SKIP: restart already in flight (lock: '{0}', {1:N0}s old, TTL {2}s) -- " -f $lockOwner, $lockAgeSec, $RestartLockTTL) `
                + "not force-killing, avoiding restart-storm collision"
            Trim-Log
            exit 0
        }
    }
    catch {
        Write-Log "WARN: cannot read restart lock -- proceeding rather than blocking indefinitely"
    }
}

if (-not $DryRun) {
    "engine-watchdog.ps1 pid=$PID host=$env:COMPUTERNAME $(Get-Date -Format o)" |
        Set-Content -Path $RestartLockFile -Force
}
else {
    Write-Log "DRY-RUN: would claim restart lock at $RestartLockFile"
}
# --------------------------------------------------------------------------

# Find PID(s) listening on port 8010
$holders = netstat -ano -p TCP 2>$null |
    Select-String ":$Port\s" |
    Where-Object { $_ -match 'LISTENING' } |
    ForEach-Object { ($_ -split '\s+') | Select-Object -Last 1 } |
    Where-Object { $_ -match '^\d+$' } |
    ForEach-Object { [int]$_ } |
    Sort-Object -Unique

if ($holders) {
    foreach ($pid in $holders) {
        $pname = try { (Get-Process -Id $pid -ErrorAction Stop).Name } catch { 'unknown' }
        Write-Log "KILL: PID $pid ($pname) holds port $Port"
        if (-not $DryRun) {
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
            Write-Log "KILL: sent Stop-Process to PID $pid"
        }
        else {
            Write-Log "DRY-RUN: would Stop-Process -Id $pid -Force"
        }
    }
    Start-Sleep -Seconds 3
}
else {
    Write-Log "INFO: nothing listening on port $Port -- engine not running"
}

Write-Log "RESTART: invoking restart_engine.ps1"
if (-not $DryRun) {
    try {
        & "$JarvisDir\restart_engine.ps1"
        Write-Log "RESTART: restart_engine.ps1 completed (exit $LASTEXITCODE)"
    }
    catch {
        Write-Log "RESTART ERROR: $($_.Exception.Message)"
    }
}
else {
    Write-Log "DRY-RUN: would invoke restart_engine.ps1"
}

Trim-Log
