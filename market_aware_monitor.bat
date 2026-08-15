@echo off
echo 🕐 Jarvis Trading System - Market Aware Monitor
echo =============================================

REM Get current market status
python3 "C:\Users\mattm\ThinkorSwim\jarvis-trader\market_timing.py" > market_status.json

REM Extract market status
set /p market_open=<market_status.json
set /p current_time=<market_status.json
set /p day_of_week=<market_status.json

echo 📊 Market Status:
echo   Day: %day_of_week%
echo   Time: %current_time%
echo   Market Open: %market_open%

REM Check if market is open
if "%market_open%"=="true" (
    echo ✅ Market is open - Trading operations active
    echo 📊 Running full system check...
    call "C:\Users\mattm\ThinkorSwim\jarvis-trader\advanced_monitor.bat"
) else (
    echo ⏰ Market is closed - Trading operations paused
    echo 📊 Running minimal system check...
    echo   Engine status: Checking...
    curl -s http://127.0.0.1:8010/health > nul 2>&1
    if %errorlevel% equ 0 (
        echo   ✅ Engine: Online (standby)
    ) else (
        echo   ❌ Engine: Offline
    )
    echo   Dashboard: Checking...
    curl -s http://127.0.0.1:3010 > nul 2>&1
    if %errorlevel% equ 0 (
        echo   ✅ Dashboard: Online
    ) else (
        echo   ❌ Dashboard: Offline
    )
)

echo.
echo 🕐 Market-aware monitoring completed
echo =============================================
