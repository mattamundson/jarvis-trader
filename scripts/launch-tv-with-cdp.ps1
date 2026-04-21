# launch-tv-with-cdp.ps1 — Launch TradingView Desktop with Chrome DevTools Protocol enabled.
#
# Purpose: The TradingView MCP server (tradingview-mcp/) requires TV Desktop to be
# running with --remote-debugging-port=9222 so the MCP server can connect via CDP.
# TV Desktop launched from the Start menu does NOT set this flag by default,
# which leaves the MCP dormant.
#
# This script:
#   1. Checks if port 9222 is already bound (CDP already alive → exit clean)
#   2. If TV is running without CDP, logs a warning but does not kill (user may be
#      mid-session with unsaved layouts). Exits 2 to signal a config gap.
#   3. If TV is not running, launches the Store-app binary with the CDP flag.
#
# Idempotent. Safe to run on login, manually, or from another script.
#
# Logs to: $env:USERPROFILE\jarvis-tv-cdp.log (rotated when >1MB)
#
# Exit codes:
#   0 = CDP alive (already was, or was just launched)
#   1 = hard failure (binary missing, launch failed)
#   2 = soft config gap (TV running without CDP — user action needed)
#
# Usage:
#   pwsh -NoProfile -File scripts\launch-tv-with-cdp.ps1
#
# Auto-triggered via scheduled task "JARVIS-TV-CDP-AtLogon"
# (installed via scripts/install-tv-cdp-startup-task.ps1).

$ErrorActionPreference = "Stop"

# ── Config ─────────────────────────────────────────────────────────────────────
$cdpPort       = 9222
$tvBinary      = "C:\Program Files\WindowsApps\TradingView.Desktop_3.0.0.7652_x64__n534cwy3pjxzj\TradingView.exe"
$logPath       = Join-Path $env:USERPROFILE "jarvis-tv-cdp.log"
$maxLogBytes   = 1MB
$launchTimeoutSec = 15

# ── Logging ────────────────────────────────────────────────────────────────────
if ((Test-Path $logPath) -and ((Get-Item $logPath).Length -gt $maxLogBytes)) {
    $backup = "$logPath.1"
    if (Test-Path $backup) { Remove-Item $backup -Force }
    Move-Item $logPath $backup -Force
}

function Write-Log {
    param([string]$msg, [string]$level = "INFO")
    $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $line = "[$ts] [$level] $msg"
    Add-Content -Path $logPath -Value $line -Encoding UTF8
    Write-Host $line
}

Write-Log "launch-tv-with-cdp.ps1 starting"

# ── Step 1: Is CDP already alive? ──────────────────────────────────────────────
function Test-CdpAlive {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:$cdpPort/json/version" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        return $resp.StatusCode -eq 200
    } catch {
        return $false
    }
}

if (Test-CdpAlive) {
    Write-Log "CDP already alive on port $cdpPort — nothing to do"
    exit 0
}

# ── Step 2: Is TV running without CDP? ────────────────────────────────────────
$tvProcs = @(Get-Process TradingView -ErrorAction SilentlyContinue)
if ($tvProcs.Count -gt 0) {
    Write-Log "TV Desktop is running ($($tvProcs.Count) processes) but CDP port $cdpPort is not responding. User likely launched TV from Start menu (no --remote-debugging-port flag). Not killing the session — user may have unsaved layouts. Relaunch manually via: taskkill /IM TradingView.exe /F; then rerun this script." "WARN"
    exit 2
}

# ── Step 3: Launch TV with CDP flag ────────────────────────────────────────────
if (-not (Test-Path $tvBinary)) {
    Write-Log "TV binary not found at: $tvBinary. If TV was updated via the Microsoft Store, the version-stamped path may have changed. Find the new path via: Get-Process TradingView | Select Path" "ERROR"
    exit 1
}

Write-Log "Launching TV Desktop with --remote-debugging-port=$cdpPort"
try {
    Start-Process -FilePath $tvBinary -ArgumentList "--remote-debugging-port=$cdpPort"
} catch {
    Write-Log "Start-Process failed: $($_.Exception.Message)" "ERROR"
    exit 1
}

# ── Step 4: Wait for CDP to come up ────────────────────────────────────────────
$deadline = (Get-Date).AddSeconds($launchTimeoutSec)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
    if (Test-CdpAlive) {
        Write-Log "CDP alive on port $cdpPort — launch successful"
        exit 0
    }
}

Write-Log "TV launched but CDP did not bind to port $cdpPort within ${launchTimeoutSec}s. Check the Electron/Chromium version + Store sandbox restrictions." "ERROR"
exit 1
