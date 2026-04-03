@echo off
title JARVIS TRADER — Startup
color 0A

echo.
echo  ====================================================
echo   JARVIS TRADER — Starting up...
echo  ====================================================
echo.

rem ── .env check ──────────────────────────────────────────────────────────
IF NOT EXIST engine\.env (
    echo.
    echo  WARNING: engine\.env not found.
    echo  Copy engine\.env.example to engine\.env and fill in your values.
    echo  Example: copy engine\.env.example engine\.env
    echo.
    pause
)

rem [DB INIT] Initialize SQLite database (no-op if already exists, safe to run every startup)
cd /d %~dp0engine
.venv\Scripts\python init_db.py
cd /d %~dp0
echo.

echo  [1/4] Launching Engine on port 8010...
start "JARVIS ENGINE - Port 8010" cmd /k "title JARVIS ENGINE - Port 8010 && cd /d %~dp0engine && echo JARVIS Engine starting... && .venv\Scripts\python -m uvicorn main:app --port 8010"

echo  [1b/4] Waiting for Engine health check (localhost:8010/health)...
setlocal enabledelayedexpansion
set "retry_count=0"
set "max_retries=30"

:wait_engine
set /a retry_count+=1
if !retry_count! gtr !max_retries! (
    echo.
    echo  [ERROR] Engine health check failed after !max_retries! attempts. Engine may not be responding.
    echo  Please check engine logs at: engine\logs\
    timeout /t 5 /nobreak
    goto :skip_browser_open
)

curl -s --connect-timeout 2 http://localhost:8010/health > nul 2>&1
if !errorlevel! equ 0 (
    echo  ✓ Engine health check passed
    endlocal
    goto :health_ok
)

echo  Attempt !retry_count!/!max_retries! - Engine not ready, retrying in 2 seconds...
timeout /t 2 /nobreak > nul
goto :wait_engine

:health_ok

echo  [2/4] Launching Dashboard on port 3010...
start "JARVIS DASHBOARD - Port 3010" cmd /k "title JARVIS DASHBOARD - Port 3010 && cd /d %~dp0dashboard && echo JARVIS Dashboard starting... && pnpm dev"

echo  [3/4] Launching Health Monitor...
start "JARVIS HEALTH MONITOR" cmd /k "title JARVIS HEALTH MONITOR && cd /d %~dp0engine && echo JARVIS Health Monitor starting... && .venv\Scripts\python health_monitor.py"

echo  [4/4] Opening dashboard in browser...
timeout /t 2 /nobreak > nul
start http://localhost:3010

:skip_browser_open

echo.
echo  ====================================================
echo   JARVIS TRADER is running.
echo   Engine        : http://localhost:8010
echo   Dashboard     : http://localhost:3010
echo   API Docs      : http://localhost:8010/docs
echo   Health Monitor: engine/logs/health.log
echo  ====================================================
echo.
echo  Close this window when done, or press any key to exit.
pause > nul
