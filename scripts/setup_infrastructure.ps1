# JARVIS TRADER — Infrastructure Setup Script (Windows PowerShell)
# Purpose: Automated Docker Compose stack initialization for paper trading
# Run: .\scripts\setup_infrastructure.ps1
#
# What it does:
#   1. Checks Docker is installed and running
#   2. Starts PostgreSQL, Redis, QuestDB, Prometheus, Grafana
#   3. Waits for all services to become healthy
#   4. Runs database migrations (init_db.py)
#   5. Copies .env.example to .env if .env doesn't exist
#   6. Prints connection verification summary

param(
    [switch]$PaperMode = $true,
    [switch]$SkipMigrations = $false
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

Write-Host "=================================================================================" -ForegroundColor Cyan
Write-Host "JARVIS TRADER — Infrastructure Setup" -ForegroundColor Cyan
Write-Host "=================================================================================" -ForegroundColor Cyan
Write-Host ""

# ── Step 0: Utility Functions ──────────────────────────────────────────────

function Test-CommandExists {
    param([string]$Command)
    try {
        if (Get-Command $Command -ErrorAction Stop) { return $true }
    }
    catch { return $false }
}

function Test-DockerIsRunning {
    try {
        docker ps 2>&1 | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

function Wait-ServiceHealthy {
    param(
        [string]$ServiceName,
        [string]$HealthCmd,
        [int]$MaxRetries = 30,
        [int]$RetryIntervalSeconds = 2
    )

    $retries = 0
    while ($retries -lt $MaxRetries) {
        try {
            $result = Invoke-Expression $HealthCmd 2>$null
            if ($result) {
                Write-Host "✓ $ServiceName is healthy" -ForegroundColor Green
                return $true
            }
        }
        catch {
            # Service not ready yet
        }

        $retries++
        if ($retries -lt $MaxRetries) {
            Write-Host "  Waiting for $ServiceName... ($retries/$MaxRetries)" -ForegroundColor Yellow
            Start-Sleep -Seconds $RetryIntervalSeconds
        }
    }

    Write-Host "✗ $ServiceName failed to become healthy" -ForegroundColor Red
    return $false
}

# ── Step 1: Check Docker Installation ──────────────────────────────────────

Write-Host "[1/7] Checking Docker Installation..." -ForegroundColor Cyan

if (-not (Test-CommandExists "docker")) {
    Write-Host "✗ Docker is not installed" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please install Docker Desktop from: https://www.docker.com/products/docker-desktop" -ForegroundColor Yellow
    exit 1
}

Write-Host "✓ Docker is installed" -ForegroundColor Green

if (-not (Test-DockerIsRunning)) {
    Write-Host "✗ Docker is not running" -ForegroundColor Red
    Write-Host "  Start Docker Desktop and try again" -ForegroundColor Yellow
    exit 1
}

Write-Host "✓ Docker is running" -ForegroundColor Green

# Check Docker Compose version
$dockerComposeVersion = docker compose version 2>&1 | Select-Object -First 1
if ($dockerComposeVersion -match "Docker Compose") {
    Write-Host "✓ Docker Compose: $dockerComposeVersion" -ForegroundColor Green
}
else {
    Write-Host "✗ Docker Compose not found (requires Docker Desktop 3.3+)" -ForegroundColor Red
    exit 1
}

Write-Host ""

# ── Step 2: Navigate to Infrastructure Directory ────────────────────────────

Write-Host "[2/7] Setting Up Docker Compose Stack..." -ForegroundColor Cyan

$infraDir = Split-Path -Path $PSScriptRoot -Parent
$infraDir = Join-Path -Path $infraDir -ChildPath "infrastructure"

if (-not (Test-Path -Path $infraDir)) {
    Write-Host "✗ Infrastructure directory not found: $infraDir" -ForegroundColor Red
    exit 1
}

Write-Host "✓ Infrastructure directory: $infraDir" -ForegroundColor Green

Push-Location $infraDir

# ── Step 3: Start Docker Compose Stack ─────────────────────────────────────

Write-Host ""
Write-Host "[3/7] Starting Docker Compose Stack..." -ForegroundColor Cyan

if ($PaperMode) {
    Write-Host "  Using paper trading overrides..." -ForegroundColor Yellow
    docker compose -f docker-compose.yml -f docker-compose.paper.yml up -d 2>&1 | Write-Host
}
else {
    docker compose up -d 2>&1 | Write-Host
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Docker Compose startup failed" -ForegroundColor Red
    Pop-Location
    exit 1
}

Write-Host "✓ Docker Compose stack started" -ForegroundColor Green
Write-Host ""

# ── Step 4: Wait for Services to Become Healthy ────────────────────────────

Write-Host "[4/7] Waiting for Services to Become Healthy..." -ForegroundColor Cyan

$allHealthy = $true

# PostgreSQL health check
$pgHealthy = Wait-ServiceHealthy -ServiceName "PostgreSQL" -HealthCmd `
    "docker exec jarvis_postgres pg_isready -U jarvis -d jarvis_trader 2>&1 | Select-String 'accepting'"

$allHealthy = $allHealthy -and $pgHealthy

# Redis health check
$redisHealthy = Wait-ServiceHealthy -ServiceName "Redis" -HealthCmd `
    "docker exec jarvis_redis redis-cli ping 2>&1 | Select-String 'PONG'"

$allHealthy = $allHealthy -and $redisHealthy

# QuestDB health check
$questdbHealthy = Wait-ServiceHealthy -ServiceName "QuestDB" -HealthCmd `
    "curl -s http://localhost:9000/status 2>&1 | Select-String 'status'"

$allHealthy = $allHealthy -and $questdbHealthy

# Prometheus health check
$promHealthy = Wait-ServiceHealthy -ServiceName "Prometheus" -HealthCmd `
    "curl -s http://localhost:9090/-/healthy 2>&1 | Select-String 'Prometheus Server is Healthy'"

$allHealthy = $allHealthy -and $promHealthy

# Grafana health check
$grafanaHealthy = Wait-ServiceHealthy -ServiceName "Grafana" -HealthCmd `
    "curl -s http://localhost:3030/api/health 2>&1 | Select-String 'database'"

$allHealthy = $allHealthy -and $grafanaHealthy

if (-not $allHealthy) {
    Write-Host ""
    Write-Host "✗ One or more services failed health checks" -ForegroundColor Red
    Write-Host "  Run 'docker compose logs' for details" -ForegroundColor Yellow
    Pop-Location
    exit 1
}

Write-Host ""

# ── Step 5: Run Database Migrations ────────────────────────────────────────

Write-Host "[5/7] Running Database Migrations..." -ForegroundColor Cyan

if ($SkipMigrations) {
    Write-Host "  (Skipped per --SkipMigrations flag)" -ForegroundColor Yellow
}
else {
    $engineDir = Join-Path -Path $infraDir -ChildPath ".." | Join-Path -ChildPath "engine"

    if (-not (Test-Path -Path $engineDir)) {
        Write-Host "✗ Engine directory not found" -ForegroundColor Red
        Pop-Location
        exit 1
    }

    Push-Location $engineDir

    # Check if .venv exists
    if (-not (Test-Path -Path ".\.venv\Scripts\python.exe")) {
        Write-Host "✗ Python venv not found at .\.venv\Scripts\python.exe" -ForegroundColor Red
        Write-Host "  Run: python -m venv .venv" -ForegroundColor Yellow
        Pop-Location
        Pop-Location
        exit 1
    }

    Write-Host "  Running init_db.py..." -ForegroundColor Yellow

    if (Test-Path -Path "init_db.py") {
        .\.venv\Scripts\python.exe init_db.py 2>&1 | Write-Host

        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ Database migrations completed" -ForegroundColor Green
        }
        else {
            Write-Host "⚠ Database migration may have failed (check output above)" -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "⚠ init_db.py not found (skipping migrations)" -ForegroundColor Yellow
    }

    Pop-Location
}

Write-Host ""

# ── Step 6: Setup .env File ────────────────────────────────────────────────

Write-Host "[6/7] Setting Up .env Configuration..." -ForegroundColor Cyan

$engineDir = Join-Path -Path $infraDir -ChildPath ".." | Join-Path -ChildPath "engine"
$envFile = Join-Path -Path $engineDir -ChildPath ".env"
$envExampleFile = Join-Path -Path $engineDir -ChildPath ".env.example"

if (Test-Path -Path $envFile) {
    Write-Host "✓ .env already exists (no action needed)" -ForegroundColor Green
    Write-Host "  To reset: remove .env and re-run this script" -ForegroundColor Gray
}
else {
    if (-not (Test-Path -Path $envExampleFile)) {
        Write-Host "✗ .env.example not found" -ForegroundColor Red
        Pop-Location
        exit 1
    }

    Write-Host "  Copying .env.example to .env..." -ForegroundColor Yellow
    Copy-Item -Path $envExampleFile -Destination $envFile

    Write-Host "✓ Created .env from template" -ForegroundColor Green
    Write-Host ""
    Write-Host "  WARNING: You must edit the following variables in $envFile:" -ForegroundColor Yellow
    Write-Host "    - ANTHROPIC_API_KEY (required for agent pipeline)" -ForegroundColor Yellow
    Write-Host "    - IB_ACCOUNT_ID (required for IB Gateway routing)" -ForegroundColor Yellow
    Write-Host "    - POLYGON_API_KEY (recommended for market data)" -ForegroundColor Yellow
    Write-Host "    - WHATSAPP_TO (optional, for alerts)" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host ""

# ── Step 7: Print Connection Verification ─────────────────────────────────

Write-Host "[7/7] Connection Verification" -ForegroundColor Cyan
Write-Host ""

Write-Host "Database Connections:" -ForegroundColor White
Write-Host "  PostgreSQL:  postgresql://jarvis:jarvis@localhost:5432/jarvis_trader" -ForegroundColor Gray
Write-Host "  Redis:       redis://localhost:6379" -ForegroundColor Gray
Write-Host "  QuestDB:     http://localhost:9000" -ForegroundColor Gray
Write-Host ""

Write-Host "Monitoring Dashboards:" -ForegroundColor White
Write-Host "  Grafana:     http://localhost:3030 (admin / jarvis_change_me)" -ForegroundColor Gray
Write-Host "  Prometheus:  http://localhost:9090" -ForegroundColor Gray
Write-Host "  QuestDB UI:  http://localhost:9000" -ForegroundColor Gray
Write-Host ""

Write-Host "Engine Services (not yet started):" -ForegroundColor White
Write-Host "  Engine API:  http://localhost:8010" -ForegroundColor Gray
Write-Host "  Dashboard:   http://localhost:3010" -ForegroundColor Gray
Write-Host ""

# Test actual connections
Write-Host "Testing Connectivity:" -ForegroundColor White

$pgTest = docker exec jarvis_postgres pg_isready -U jarvis -d jarvis_trader 2>&1 | Select-String "accepting"
if ($pgTest) {
    Write-Host "  ✓ PostgreSQL is responsive" -ForegroundColor Green
}
else {
    Write-Host "  ✗ PostgreSQL failed connection test" -ForegroundColor Red
}

$redisTest = docker exec jarvis_redis redis-cli ping 2>&1 | Select-String "PONG"
if ($redisTest) {
    Write-Host "  ✓ Redis is responsive" -ForegroundColor Green
}
else {
    Write-Host "  ✗ Redis failed connection test" -ForegroundColor Red
}

try {
    $questTest = curl -s http://localhost:9000/status 2>&1 | Select-String "status"
    if ($questTest) {
        Write-Host "  ✓ QuestDB is responsive" -ForegroundColor Green
    }
    else {
        Write-Host "  ⚠ QuestDB may not be fully initialized" -ForegroundColor Yellow
    }
}
catch {
    Write-Host "  ⚠ Could not verify QuestDB (may still be starting)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=================================================================================" -ForegroundColor Cyan
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "=================================================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Next Steps:" -ForegroundColor White
Write-Host "  1. Edit engine/.env and fill in required API keys:" -ForegroundColor White
Write-Host "     - ANTHROPIC_API_KEY" -ForegroundColor Gray
Write-Host "     - IB_ACCOUNT_ID" -ForegroundColor Gray
Write-Host "     - POLYGON_API_KEY (optional but recommended)" -ForegroundColor Gray
Write-Host ""
Write-Host "  2. Ensure IB Gateway is running on localhost:7497 (paper trading port)" -ForegroundColor White
Write-Host ""
Write-Host "  3. Start the Engine:" -ForegroundColor White
Write-Host "     cd engine && .\.venv\Scripts\python -m uvicorn main:app --reload --port 8010" -ForegroundColor Gray
Write-Host ""
Write-Host "  4. Start the Dashboard (in new terminal):" -ForegroundColor White
Write-Host "     cd dashboard && pnpm dev" -ForegroundColor Gray
Write-Host ""
Write-Host "  5. Verify health checks:" -ForegroundColor White
Write-Host "     curl http://localhost:8010/health" -ForegroundColor Gray
Write-Host ""

Write-Host "For more details, see: docs/runbooks/PAPER_TRADING.md" -ForegroundColor Cyan
Write-Host ""

Pop-Location
