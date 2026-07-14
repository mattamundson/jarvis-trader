@echo off
echo 🚨 Jarvis Trading System Alerting - %date% %time%
echo =============================================

REM Check engine health
engine_health=curl -s http://127.0.0.1:8010/health 2^>nul
if %errorlevel% neq 0 (
    echo 🚨 CRITICAL: Engine is offline!
    echo   Action: Restart engine immediately
    echo   Alert: Engine offline - %date% %time% >> C:\tmp\jarvis_alerts.log
)

REM Check if kill switch is active
if "%engine_health%" == *"kill_switch_active":true"* (
    echo 🚨 CRITICAL: Kill switch is active!
    echo   Action: Check if this is intentional or needs deactivation
    echo   Alert: Kill switch active - %date% %time% >> C:\tmp\jarvis_alerts.log
)

REM Check LLM provider health
if "%engine_health%" == *"primary_healthy":false"* (
    echo 🚨 WARNING: Primary LLM provider is unhealthy
    echo   Action: Check LLM provider configuration
    echo   Alert: LLM provider unhealthy - %date% %time% >> C:\tmp\jarvis_alerts.log
)

REM Check IBKR connection
if "%engine_health%" == *"ibkr_connected":false"* (
    echo 🚨 CRITICAL: IBKR connection lost!
    echo   Action: Check IBKR connection and credentials
    echo   Alert: IBKR connection lost - %date% %time% >> C:\tmp\jarvis_alerts.log
)

REM Check dashboard
dashboard_health=curl -s http://127.0.0.1:3010 2^>nul
if %errorlevel% neq 0 (
    echo 🚨 WARNING: Dashboard is offline
    echo   Action: Check dashboard service
    echo   Alert: Dashboard offline - %date% %time% >> C:\tmp\jarvis_alerts.log
)

echo.
echo 📊 Alert check completed at %date% %time%
echo =============================================
