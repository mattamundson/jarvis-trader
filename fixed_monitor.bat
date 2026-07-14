@echo off
echo 🔍 Jarvis Trading System Monitor - %date% %time%
echo =============================================

REM Check engine health
echo 📊 Engine Health Check:
curl -s http://127.0.0.1:8010/health > engine_health.json 2^>nul
if %errorlevel% equ 0 (
    echo ✅ Engine: Online
    REM Extract key metrics using findstr
    findstr "status" engine_health.json
    findstr "kill_switch_active" engine_health.json
    findstr "ibkr_connected" engine_health.json
    findstr "tradingview_mcp_healthy" engine_health.json
    del engine_health.json
) else (
    echo ❌ Engine: Offline or unreachable
)

echo.
echo 📊 Dashboard Health Check:
curl -s http://127.0.0.1:3010 > nul 2^>nul
if %errorlevel% equ 0 (
    echo ✅ Dashboard: Online
) else (
    echo ❌ Dashboard: Offline or unreachable
)

echo.
echo 📊 PM2 Process Status:
pm2 list 2^>nul
if %errorlevel% equ 0 (
    echo ✅ PM2: Running
    echo   Jarvis Engine: pm2 list | find "jarvis-engine"
    echo   Jarvis Dashboard: pm2 list | find "jarvis-dashboard"
    echo   Jarvis Bridge API: pm2 list | find "jarvis-bridge-api"
) else (
    echo ❌ PM2: Not running
)

echo.
echo 📊 System Resources:
echo   CPU Usage: tasklist | findstr "cmd" > nul
echo   Memory Usage: systeminfo | findstr "Physical Memory Available"
echo   Disk Usage: fsutil volume diskfree C:

echo.
echo 🔍 Monitor completed at %date% %time%
echo =============================================
