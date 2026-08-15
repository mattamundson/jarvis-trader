@echo off
echo 🕐 Jarvis Trading System - Market Status
echo =============================================

REM Get current date and time
for /f "tokens=1-4 delims=/ " %%a in ('date /t') do set today=%%c-%%a-%%b
for /f "tokens=1-2 delims=: " %%a in ('time /t') do set current_time=%%a:%%b

echo 📊 Current Status:
echo   Date: %today%
echo   Time: %current_time%

REM Check day of week
set day=0
for /f "tokens=1-7 delims= " %%a in ('wmic path win32_localtime get dayofweek /value ^| find "="') do (
    if "%%a"=="DayOfWeek=" set day=%%b
)

REM Check market hours (9:30 AM - 4:00 PM ET, Monday-Friday)
set market_open=false
if %day% LSS 6 (
    REM Monday-Friday
    set hour=%current_time:~0,2%
    set minute=%current_time:~3,2%
    
    if %hour% GTR 8 (
        if %hour% LSS 16 (
            set market_open=true
        ) else if %hour% EQU 16 (
            if %minute% LSS 1 (
                set market_open=true
            )
        )
    ) else if %hour% EQU 8 (
        if %minute% GTR 29 (
            set market_open=true
        )
    )
)

echo   Day of Week: %day%
echo   Market Open: %market_open%

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
echo 🕐 Market status check completed
echo =============================================
