@echo off
echo 🔍 Jarvis Trading System Monitor - %date% %time%
echo =============================================

REM Check engine health
echo 📊 Engine Health Check:
engine_health=curl -s http://127.0.0.1:8010/health 2^>nul
if %errorlevel% equ 0 (
    echo ✅ Engine: Online
    REM Extract key metrics using findstr
    echo   Status: %engine_health% | findstr "status"
    echo   Kill Switch: %engine_health% | findstr "kill_switch_active"
    echo   IBKR Connected: %engine_health% | findstr "ibkr_connected"
    echo   TradingView MCP: %engine_health% | findstr "tradingview_mcp_healthy"
) else (
    echo ❌ Engine: Offline or unreachable
)

echo.
echo 📊 Dashboard Health Check:
dashboard_health=curl -s http://127.0.0.1:3010 2^>nul
if %errorlevel% equ 0 (
    echo ✅ Dashboard: Online
    echo   Response Size: %dashboard_health% | find /c ">"
) else (
    echo ❌ Dashboard: Offline or unreachable
)

echo.
echo 📊 PM2 Process Status:
pm2_status=pm2 list 2^>nul
if %errorlevel% equ 0 (
    echo ✅ PM2: Running
    echo   Jarvis Engine: %pm2_status% | find "jarvis-engine"
    echo   Jarvis Dashboard: %pm2_status% | find "jarvis-dashboard"
    echo   Jarvis Bridge API: %pm2_status% | find "jarvis-bridge-api"
) else (
    echo ❌ PM2: Not running
)

echo.
echo 📊 System Resources:
echo   CPU Usage: tasklist | findstr "cmd" > nul
echo   Memory Usage: systeminfo | findstr "Physical Memory Available"
echo   Disk Usage: fsutil volume diskfree C:

echo.
echo 📊 Network Connectivity:
echo   IBKR Port: netstat -an | find ":4002" | find "LISTENing" | find /c ">"
echo   Engine Port: netstat -an | find ":8010" | find "LISTENing" | find /c ">"
echo   Dashboard Port: netstat -an | find ":3010" | find "LISTENing" | find /c ">"
echo   TradingView CDP: netstat -an | find ":9222" | find "LISTENing" | find /c ">"

echo.
echo 🔍 Monitor completed at %date% %time%
echo =============================================
