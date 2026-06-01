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

$EngineUrl  = 'http://127.0.0.1:8010/health'
$Port       = 8010
$JarvisDir  = 'C:\Users\mattm\ThinkorSwim\jarvis-trader'
$LogDir     = "$JarvisDir\logs"
$LogFile    = "$LogDir\engine-watchdog.log"
$MaxLogKB   = 512

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
    } catch {}
}

# Check health
$healthy = $false
try {
    $resp = Invoke-WebRequest -Uri $EngineUrl -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop
    if ($resp.StatusCode -eq 200) { $healthy = $true }
} catch {}

if ($healthy) {
    # Silent on success -- log would fill up every 5 min
    exit 0
}

Write-Log "FAIL: /health unresponsive -- checking port $Port"

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
        } else {
            Write-Log "DRY-RUN: would Stop-Process -Id $pid -Force"
        }
    }
    Start-Sleep -Seconds 3
} else {
    Write-Log "INFO: nothing listening on port $Port -- engine not running"
}

Write-Log "RESTART: invoking restart_engine.ps1"
if (-not $DryRun) {
    try {
        & "$JarvisDir\restart_engine.ps1"
        Write-Log "RESTART: restart_engine.ps1 completed (exit $LASTEXITCODE)"
    } catch {
        Write-Log "RESTART ERROR: $($_.Exception.Message)"
    }
} else {
    Write-Log "DRY-RUN: would invoke restart_engine.ps1"
}

Trim-Log
