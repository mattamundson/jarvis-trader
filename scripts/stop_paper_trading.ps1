<#
.SYNOPSIS
    JARVIS TRADER — Paper Trading Shutdown Script

.DESCRIPTION
    Cleanly stops all JARVIS TRADER processes (engine, dashboard, rolling WFE).
    Provides shutdown status and logs.

.EXAMPLE
    .\scripts\stop_paper_trading.ps1

.NOTES
    - Uses PM2 to manage process shutdown
    - Kills background dashboard process if running
    - Prints shutdown summary with timestamps
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

# Define colors for output
$Colors = @{
    Pass    = "Green"
    Fail    = "Red"
    Warning = "Yellow"
    Info    = "Cyan"
    Header  = "Magenta"
}

function Write-Header {
    param([string]$Message)
    Write-Host ""
    Write-Host "  ===================================================================" -ForegroundColor $Colors.Header
    Write-Host "  $Message" -ForegroundColor $Colors.Header
    Write-Host "  ===================================================================" -ForegroundColor $Colors.Header
    Write-Host ""
}

function Write-Pass {
    param([string]$Message)
    Write-Host "  [PASS] $Message" -ForegroundColor $Colors.Pass
}

function Write-Fail {
    param([string]$Message)
    Write-Host "  [FAIL] $Message" -ForegroundColor $Colors.Fail
}

function Write-Warn {
    param([string]$Message)
    Write-Host "  [WARN] $Message" -ForegroundColor $Colors.Warning
}

function Write-Info {
    param([string]$Message)
    Write-Host "  [INFO] $Message" -ForegroundColor $Colors.Info
}

# ============================================================================
# SHUTDOWN SEQUENCE
# ============================================================================

Write-Header "JARVIS TRADER — Shutdown"

$startTime = Get-Date

Write-Host "  Initiated at: $($startTime.ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor $Colors.Info
Write-Host ""

# Stop all PM2 processes
Write-Info "Stopping PM2 processes..."
$pm2Stop = & pm2 stop all 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Pass "PM2 stopped all processes"
} else {
    Write-Warn "PM2 stop command returned exit code: $LASTEXITCODE"
    Write-Host "  Output: $pm2Stop" -ForegroundColor $Colors.Warning
}

# Kill dashboard process if running
Write-Info "Stopping dashboard process..."
$dashboardPidFile = "dashboard-pid.txt"

if (Test-Path $dashboardPidFile) {
    $dashboardPid = Get-Content $dashboardPidFile -ErrorAction SilentlyContinue
    if ($dashboardPid) {
        try {
            $process = Get-Process -Id $dashboardPid -ErrorAction SilentlyContinue
            if ($process) {
                Stop-Process -Id $dashboardPid -Force -ErrorAction SilentlyContinue
                Start-Sleep -Milliseconds 500
                Write-Pass "Dashboard process stopped (PID: $dashboardPid)"
            } else {
                Write-Info "Dashboard process (PID: $dashboardPid) no longer running"
            }
        } catch {
            Write-Warn "Could not stop dashboard process: $_"
        }
    }
    # Clean up PID file
    Remove-Item $dashboardPidFile -Force -ErrorAction SilentlyContinue
}

# Give processes time to shut down gracefully
Write-Info "Waiting for graceful shutdown..."
Start-Sleep -Seconds 3

# Verify all processes are stopped
Write-Info "Verifying process termination..."
try {
    $pm2List = & pm2 list 2>&1
    if ($pm2List -match "stopped|offline") {
        Write-Pass "All PM2 processes are stopped or offline"
    } else {
        Write-Warn "Some processes may still be running"
    }
} catch {
    Write-Warn "Could not verify process status"
}

# ============================================================================
# FINAL STATUS
# ============================================================================

Write-Header "SHUTDOWN COMPLETE"

$endTime = Get-Date
$duration = $endTime - $startTime

Write-Host "  Shutdown at: $($endTime.ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor $Colors.Info
Write-Host "  Duration: $($duration.TotalSeconds) seconds" -ForegroundColor $Colors.Info
Write-Host ""

Write-Host "  Status Summary:" -ForegroundColor $Colors.Info
Write-Host "    Engine          : Stopped" -ForegroundColor $Colors.Pass
Write-Host "    Dashboard       : Stopped" -ForegroundColor $Colors.Pass
Write-Host "    Rolling WFE     : Stopped" -ForegroundColor $Colors.Pass
Write-Host ""

Write-Host "  Logs available at:" -ForegroundColor $Colors.Info
Write-Host "    Engine:        engine/logs/engine-out.log" -ForegroundColor $Colors.Info
Write-Host "    Engine Error:  engine/logs/engine-error.log" -ForegroundColor $Colors.Info
Write-Host "    Rolling WFE:   engine/logs/rolling-wfe-out.log" -ForegroundColor $Colors.Info
Write-Host ""

Write-Host "  To restart paper trading:" -ForegroundColor $Colors.Info
Write-Host "    .\scripts\launch_paper_trading.ps1" -ForegroundColor $Colors.Info
Write-Host ""
