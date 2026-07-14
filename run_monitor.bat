@echo off
echo Running Jarvis Trading System Monitor...
echo.

REM Run advanced monitoring
echo ==========================================
echo 📊 Advanced Monitor
echo ==========================================
call "C:\Users\mattm\ThinkorSwim\jarvis-trader\advanced_monitor.sh"

echo.
echo ==========================================
echo 🚨 Alert System Check  
echo ==========================================
call "C:\Users\mattm\ThinkorSwim\jarvis-trader\alerting_system.sh"

echo.
echo ==========================================
echo 📊 Dashboard Health Check
echo ==========================================
curl -s http://127.0.0.1:3010 > nul 2>&1
if %errorlevel% equ 0 (
    echo ✅ Dashboard: Online
) else (
    echo ❌ Dashboard: Offline
)

echo.
echo Monitor completed at %date% %time%
