@echo off
REM ============================================================
REM JARVIS TRADER — Paper Trading Boot Script
REM Run this from: C:\Users\mattm\ThinkorSwim\jarvis-trader
REM Prerequisites: IB Gateway logged in (wolfof216, port 4002)
REM ============================================================

echo.
echo ====================================
echo  JARVIS TRADER — Paper Trading Boot
echo ====================================
echo.

REM ── Step 1: Docker services ────────────────────────────────
echo [1/4] Starting Docker Compose services...
cd /d "C:\Users\mattm\ThinkorSwim\jarvis-trader\infrastructure"
docker compose up -d
if %ERRORLEVEL% NEQ 0 (
    echo WARNING: Docker compose failed. Is Docker Desktop running?
    echo Continuing anyway — engine can run without Docker services.
)
echo.

REM ── Step 2: Verify IB Gateway port ────────────────────────
echo [2/4] Checking IB Gateway on port 4002...
powershell -NoProfile -Command "if ((Test-NetConnection -ComputerName 127.0.0.1 -Port 4002 -WarningAction SilentlyContinue).TcpTestSucceeded) { Write-Host 'IB Gateway: CONNECTED on port 4002' -ForegroundColor Green } else { Write-Host 'IB Gateway: NOT REACHABLE on port 4002' -ForegroundColor Red; Write-Host 'Please start IB Gateway and log in first.' }"
echo.

REM ── Step 3: Start Engine ───────────────────────────────────
echo [3/4] Starting JARVIS Engine on port 8010...
echo      Client ID: 2 (from .env IBKR_CLIENT_ID=2)
echo      Paper Trading Mode: ON
echo.
cd /d "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine"
start "JARVIS Engine" cmd /k ".venv\Scripts\python" -m uvicorn main:app --port 8010

REM Wait for engine to initialize
echo Waiting 15 seconds for engine startup...
timeout /t 15 /nobreak > nul

REM ── Step 4: Verify engine health ───────────────────────────
echo [4/4] Checking engine health...
powershell -NoProfile -Command "try { $r = Invoke-RestMethod -Uri 'http://localhost:8010/health' -TimeoutSec 10; Write-Host ('Engine: ' + $r.status) -ForegroundColor Green; Write-Host ('Paper Mode: ' + $r.paper_mode); Write-Host ('IBKR Connected: ' + $r.ibkr_connected); Write-Host ('Kill Switch: ' + $r.kill_switch_active) } catch { Write-Host 'Engine not responding yet. Give it a few more seconds.' -ForegroundColor Yellow }"
echo.

REM ── Step 5: Start Dashboard ────────────────────────────────
echo Starting Dashboard on port 3010...
cd /d "C:\Users\mattm\ThinkorSwim\jarvis-trader\dashboard"
start "JARVIS Dashboard" cmd /k pnpm dev

echo.
echo ====================================
echo  Boot complete. Check the windows:
echo  - Engine: http://localhost:8010
echo  - Dashboard: http://localhost:3010
echo  - API Docs: http://localhost:8010/docs
echo ====================================
echo.
pause
