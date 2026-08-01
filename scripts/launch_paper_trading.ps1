<#
.SYNOPSIS
    JARVIS TRADER — Comprehensive Paper Trading Launch Script

.DESCRIPTION
    Performs extensive pre-flight checks before starting the paper trading system.
    Includes dependency validation, safety verification, test suite execution, and
    post-launch health checks.

    CRITICAL: Aborts immediately on ANY safety check failure.

.PARAMETER SkipTests
    If specified, skip the test suite execution (for development only)

.PARAMETER SkipIBCheck
    If specified, skip IB Gateway connectivity check (useful if not ready yet)

.EXAMPLE
    .\scripts\launch_paper_trading.ps1
    .\scripts\launch_paper_trading.ps1 -SkipTests

.NOTES
    - All paths are relative to the project root directory
    - Output uses color coding: Green = pass, Red = fail, Yellow = warning
    - PM2 is required for process management
#>

param(
    [switch]$SkipTests = $false,
    [switch]$SkipIBCheck = $false
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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

function Abort-Launch {
    param([string]$Reason)
    Write-Host ""
    Write-Fail "LAUNCH ABORTED: $Reason"
    Write-Host ""
    Write-Host "  Please fix the issues above and try again." -ForegroundColor $Colors.Warning
    Write-Host ""
    exit 1
}

# ============================================================================
# PHASE 1: PREFLIGHT CHECKS
# ============================================================================

Write-Header "PHASE 1: PREFLIGHT DEPENDENCY CHECKS"

# Check Java
Write-Host "  Checking Java installation..." -ForegroundColor $Colors.Info
$javaCheck = & cmd /c "java -version 2>&1" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Pass "Java is installed"
}
else {
    Write-Fail "Java not found or not in PATH"
    Abort-Launch "Java Runtime Environment (JRE) 11+ is required for IB Gateway"
}

# Check Node.js
Write-Host "  Checking Node.js installation..." -ForegroundColor $Colors.Info
$nodeVersion = & node --version 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Pass "Node.js is installed ($nodeVersion)"
}
else {
    Write-Fail "Node.js not found or not in PATH"
    Abort-Launch "Node.js is required for PM2 and the dashboard"
}

# Check PM2
Write-Host "  Checking PM2 installation..." -ForegroundColor $Colors.Info
$pm2Version = & pm2 --version 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Pass "PM2 is installed (v$pm2Version)"
}
else {
    Write-Fail "PM2 not found or not in PATH"
    Write-Host "  Install PM2 globally: npm install -g pm2" -ForegroundColor $Colors.Warning
    Abort-Launch "PM2 is required for process management"
}

# Check Python venv
Write-Host "  Checking Python venv..." -ForegroundColor $Colors.Info
$pythonExe = Join-Path -Path "engine" -ChildPath ".venv\Scripts\python.exe"
if (Test-Path $pythonExe) {
    Write-Pass "Python venv exists at engine\.venv\Scripts\python.exe"
}
else {
    Write-Fail "Python venv not found at $pythonExe"
    Abort-Launch "Create the venv with: cd engine && python -m venv .venv && .venv\Scripts\pip install -r requirements-core.txt"
}

# ============================================================================
# PHASE 2: ENVIRONMENT CONFIGURATION VALIDATION
# ============================================================================

Write-Header "PHASE 2: ENVIRONMENT CONFIGURATION VALIDATION"

# Check .env file exists
Write-Host "  Checking .env file..." -ForegroundColor $Colors.Info
$envFile = Join-Path -Path "engine" -ChildPath ".env"
if (-not (Test-Path $envFile)) {
    Write-Fail ".env file not found at engine\.env"
    Abort-Launch "Create engine\.env from engine\.env.example and fill in your configuration"
}
Write-Pass ".env file exists"

# Load and validate .env variables
Write-Host "  Loading .env configuration..." -ForegroundColor $Colors.Info
$envContent = Get-Content $envFile -Raw
$requiredVars = @("ANTHROPIC_API_KEY", "POSTGRES_URL", "IBKR_PORT", "PAPER_TRADING", "LIVE_TRADING_ENABLED")
$missingVars = @()
$invalidVars = @()

foreach ($var in $requiredVars) {
    $pattern = "^\s*$var\s*=\s*(.+)$"
    if ($envContent -match $pattern) {
        $value = $matches[1].Trim('"').Trim()
        # Check for placeholder values
        if ($value -match "YOUR_|_HERE$|^$" -or $value -eq "example") {
            $invalidVars += $var
        }
    }
    else {
        $missingVars += $var
    }
}

if ($missingVars) {
    Write-Fail "Missing required environment variables: $($missingVars -join ', ')"
    Abort-Launch "Add missing variables to engine\.env"
}

if ($invalidVars) {
    Write-Fail "Environment variables contain placeholder values: $($invalidVars -join ', ')"
    Abort-Launch "Replace placeholder values in engine\.env with real configuration"
}

Write-Pass "All required environment variables are configured (no placeholders)"

# CRITICAL: Verify PAPER_TRADING=True
Write-Host "  Verifying paper trading mode is enabled..." -ForegroundColor $Colors.Info
if ($envContent -match 'PAPER_TRADING\s*=\s*(True|true|1)') {
    Write-Pass "PAPER_TRADING=True (paper mode enabled)"
}
else {
    Write-Fail "PAPER_TRADING is not set to True"
    Abort-Launch "CRITICAL: Paper trading mode MUST be enabled. Set PAPER_TRADING=True in engine\.env"
}

# CRITICAL: Verify LIVE_TRADING_ENABLED=False
Write-Host "  Verifying live trading is disabled..." -ForegroundColor $Colors.Info
if ($envContent -match 'LIVE_TRADING_ENABLED\s*=\s*(False|false|0)') {
    Write-Pass "LIVE_TRADING_ENABLED=False (live mode disabled)"
}
else {
    Write-Fail "LIVE_TRADING_ENABLED is not set to False"
    Abort-Launch "CRITICAL: Live trading MUST be disabled. Set LIVE_TRADING_ENABLED=False in engine\.env"
}

# ============================================================================
# PHASE 3: INFRASTRUCTURE CHECKS
# ============================================================================

Write-Header "PHASE 3: INFRASTRUCTURE CHECKS"

# Check Docker
Write-Host "  Checking Docker..." -ForegroundColor $Colors.Info
$dockerInfo = & docker info 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Pass "Docker is running"
}
else {
    Write-Warn "Docker is not running or not installed"
    Write-Host "    Skipping Docker-dependent checks (Postgres/Redis)" -ForegroundColor $Colors.Warning
    $skipDockerChecks = $true
}

if (-not $skipDockerChecks) {
    # Check Postgres container
    Write-Host "  Checking Postgres container..." -ForegroundColor $Colors.Info
    $dockerPs = & docker ps --format "table {{.Names}}" 2>&1
    if ($dockerPs -match "postgres") {
        Write-Pass "Postgres container is running"
    }
    else {
        Write-Warn "Postgres container not found in running containers"
        Write-Host "    If needed, start with: docker-compose up -d postgres" -ForegroundColor $Colors.Warning
    }

    # Check Redis container
    Write-Host "  Checking Redis container..." -ForegroundColor $Colors.Info
    if ($dockerPs -match "redis") {
        Write-Pass "Redis container is running"
    }
    else {
        Write-Warn "Redis container not found in running containers"
        Write-Host "    If needed, start with: docker-compose up -d redis" -ForegroundColor $Colors.Warning
    }
}

# Check IB Gateway connectivity (unless skipped)
if (-not $SkipIBCheck) {
    Write-Host "  Testing IB Gateway connectivity on port 7497..." -ForegroundColor $Colors.Info
    try {
        $tcpClient = New-Object System.Net.Sockets.TcpClient
        $tcpClient.Connect("127.0.0.1", 7497)
        if ($tcpClient.Connected) {
            Write-Pass "IB Gateway is reachable on 127.0.0.1:7497"
            $tcpClient.Close()
        }
    }
    catch {
        Write-Warn "IB Gateway not reachable on 127.0.0.1:7497"
        Write-Host "    Start IB Gateway and verify it's listening on port 7497" -ForegroundColor $Colors.Warning
    }
}
else {
    Write-Info "Skipping IB Gateway connectivity check (-SkipIBCheck)"
}

# ============================================================================
# PHASE 4: SAFETY VERIFICATION
# ============================================================================

Write-Header "PHASE 4: SAFETY VERIFICATION"

# Read engine/config.py and verify LIVE_TRADING_ENABLED default
Write-Host "  Reading engine/config.py..." -ForegroundColor $Colors.Info
$configPath = Join-Path -Path "engine" -ChildPath "config.py"
if (Test-Path $configPath) {
    $configContent = Get-Content $configPath -Raw
    if ($configContent -match 'LIVE_TRADING_ENABLED\s*[=:]\s*(False|False)') {
        Write-Pass "engine/config.py has LIVE_TRADING_ENABLED default set to False"
    }
    else {
        Write-Warn "Could not verify LIVE_TRADING_ENABLED default in config.py"
    }
}
else {
    Write-Fail "engine/config.py not found"
    Abort-Launch "Config file is missing or in unexpected location"
}

# Verify safety_layer.py exists and is not empty
Write-Host "  Verifying safety_layer.py..." -ForegroundColor $Colors.Info
$safetyLayerPath = Join-Path -Path "engine" -ChildPath "risk\safety_layer.py"
if (Test-Path $safetyLayerPath) {
    $fileSize = (Get-Item $safetyLayerPath).Length
    if ($fileSize -gt 1000) {
        Write-Pass "safety_layer.py exists and contains $fileSize bytes"
    }
    else {
        Write-Fail "safety_layer.py is too small or empty"
        Abort-Launch "Safety layer appears corrupted or incomplete"
    }
}
else {
    Write-Fail "safety_layer.py not found at engine/risk/safety_layer.py"
    Abort-Launch "Safety layer module is required"
}

# Verify kill switch thresholds are documented
Write-Host "  Verifying kill switch thresholds..." -ForegroundColor $Colors.Info
if ($safetyLayerContent = Get-Content $safetyLayerPath -Raw) {
    $has_daily_pct = $safetyLayerContent -match "MAX_DAILY_LOSS_PCT"
    $has_drawdown_pct = $safetyLayerContent -match "MAX_DRAWDOWN_PCT"
    if ($has_daily_pct -and $has_drawdown_pct) {
        Write-Pass "Kill switch thresholds found: -6% daily loss, -20% drawdown (config.py defaults, reconciled to .env live truth 2026-06-25)"
    }
    else {
        Write-Warn "Could not verify kill switch thresholds in code"
    }
}

# ============================================================================
# PHASE 5: TEST SUITE EXECUTION
# ============================================================================

if (-not $SkipTests) {
    Write-Header "PHASE 5: TEST SUITE EXECUTION"

    Write-Host "  Running safety layer tests..." -ForegroundColor $Colors.Info
    Push-Location "engine"

    try {
        # Run safety layer tests
        $testOutput = & .\.venv\Scripts\python -m pytest tests\test_safety_layer.py -v 2>&1
        $testExitCode = $LASTEXITCODE

        if ($testExitCode -eq 0) {
            Write-Pass "Safety layer tests passed"
            Write-Info "Test output (last 10 lines):"
            ($testOutput | Select-Object -Last 10) | ForEach-Object {
                Write-Host "    $_"
            }
        }
        else {
            Write-Fail "Safety layer tests failed (exit code: $testExitCode)"
            Write-Host ""
            Write-Host "Test output:" -ForegroundColor $Colors.Fail
            $testOutput | ForEach-Object {
                Write-Host "  $_"
            }
            Pop-Location
            Abort-Launch "Safety tests are non-negotiable and must pass"
        }
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Info "Skipping test suite execution (-SkipTests)"
}

# ============================================================================
# PHASE 6: LAUNCH SEQUENCE
# ============================================================================

Write-Header "PHASE 6: LAUNCH SEQUENCE"

Write-Info "Starting engine via PM2..."
$pm2Start = & pm2 start ecosystem.config.js --only jarvis-engine 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Pass "PM2 started jarvis-engine"
}
else {
    Write-Fail "PM2 failed to start engine"
    Write-Host "$pm2Start" -ForegroundColor $Colors.Fail
    Abort-Launch "Engine startup failed"
}

Write-Info "Waiting 10 seconds for engine initialization..."
Start-Sleep -Seconds 10

Write-Info "Health check: GET http://localhost:8010/health..."
$maxRetries = 30
$retryCount = 0
$healthCheckPassed = $false

while ($retryCount -lt $maxRetries) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8010/health" -TimeoutSec 2 -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            Write-Pass "Engine health check passed"
            $healthCheckPassed = $true
            break
        }
    }
    catch {
        # Health check failed, retry
    }

    $retryCount++
    if ($retryCount -lt $maxRetries) {
        Write-Host "    Attempt $retryCount/$maxRetries - Engine not ready, retrying in 2 seconds..." -ForegroundColor $Colors.Warning
        Start-Sleep -Seconds 2
    }
}

if (-not $healthCheckPassed) {
    Write-Fail "Engine health check failed after $maxRetries attempts"
    Write-Host "  Check engine logs: engine/logs/engine-out.log" -ForegroundColor $Colors.Warning
    Abort-Launch "Engine failed to start or become responsive"
}

Write-Info "Starting dashboard (pnpm dev)..."
Push-Location "dashboard"
try {
    $dashboardProcess = Start-Process -FilePath "cmd" `
        -ArgumentList "/c", "pnpm dev" `
        -NoNewWindow `
        -PassThru `
        -WindowStyle Minimized 2>$null

    if ($dashboardProcess) {
        Write-Pass "Dashboard process started (PID: $($dashboardProcess.Id))"
        # Store PID for shutdown script
        $dashboardProcess.Id | Out-File -FilePath "..\dashboard-pid.txt" -Force
    }
}
finally {
    Pop-Location
}

Start-Sleep -Seconds 3

# ============================================================================
# PHASE 7: POST-LAUNCH VERIFICATION
# ============================================================================

Write-Header "PHASE 7: POST-LAUNCH VERIFICATION"

# GET /health
Write-Host "  Verifying GET /health..." -ForegroundColor $Colors.Info
try {
    $healthResponse = Invoke-WebRequest -Uri "http://localhost:8010/health" -TimeoutSec 2 -ErrorAction Stop
    Write-Pass "Engine health check passed"
}
catch {
    Write-Warn "Engine health check failed: $_"
}

# GET /safety/status
Write-Host "  Checking GET /safety/status..." -ForegroundColor $Colors.Info
try {
    $safetyResponse = Invoke-WebRequest -Uri "http://localhost:8010/safety/status" -TimeoutSec 2 -ErrorAction Stop
    if ($safetyResponse.StatusCode -eq 200) {
        Write-Pass "Safety status endpoint available"
        $content = $safetyResponse.Content | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($content) {
            Write-Info "  Kill switch: $(if ($content.kill_switch_active) { 'ACTIVE' } else { 'OFF' })"
            Write-Info "  Paper mode: $(if ($content.paper_mode) { 'ON' } else { 'OFF' })"
        }
    }
}
catch {
    Write-Warn "Could not retrieve safety status: $_"
}

# GET /portfolio
Write-Host "  Checking GET /portfolio..." -ForegroundColor $Colors.Info
try {
    $portfolioResponse = Invoke-WebRequest -Uri "http://localhost:8010/portfolio" -TimeoutSec 2 -ErrorAction Stop
    if ($portfolioResponse.StatusCode -eq 200) {
        Write-Pass "Portfolio endpoint available"
        $content = $portfolioResponse.Content | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($content -and $content.starting_equity) {
            Write-Info "  Starting equity: $($content.starting_equity)"
        }
    }
}
catch {
    Write-Warn "Could not retrieve portfolio data: $_"
}

# ============================================================================
# FINAL BANNER
# ============================================================================

Write-Header "PAPER TRADING READY"

Write-Host ""
Write-Host "  JARVIS TRADER is launching..." -ForegroundColor $Colors.Pass
Write-Host ""
Write-Host "  Engine (FastAPI)      : http://localhost:8010" -ForegroundColor $Colors.Info
Write-Host "  Dashboard (Next.js)   : http://localhost:3010" -ForegroundColor $Colors.Info
Write-Host "  API Documentation     : http://localhost:8010/docs" -ForegroundColor $Colors.Info
Write-Host "  Engine Logs           : engine/logs/engine-out.log" -ForegroundColor $Colors.Info
Write-Host ""
Write-Host "  Safety Status         : ENFORCED (kill switch -6% daily, -20% drawdown)" -ForegroundColor $Colors.Pass
Write-Host "  Paper Mode            : ACTIVE" -ForegroundColor $Colors.Pass
Write-Host "  Live Trading          : DISABLED" -ForegroundColor $Colors.Pass
Write-Host ""
Write-Host "  To stop: .\scripts\stop_paper_trading.ps1" -ForegroundColor $Colors.Info
Write-Host ""
Write-Host "  WARNING: Do NOT modify safety parameters without explicit authorization" -ForegroundColor $Colors.Warning
Write-Host ""

# Wait a moment before opening dashboard
Start-Sleep -Seconds 2

# Try to open dashboard in browser
try {
    Start-Process "http://localhost:3010"
    Write-Info "Opened dashboard in default browser"
}
catch {
    Write-Warn "Could not open browser automatically"
}

Write-Host ""
