@echo off
echo Checking TradingView CDP status...
echo.

REM Check if port 9222 is listening
netstat -an | find ":9222" | find "LISTENING"
if %errorlevel% equ 0 (
    echo ✅ Port 9222 is listening
    echo TradingView CDP is ready
) else (
    echo ❌ Port 9222 is not listening
    echo TradingView may not be running with CDP enabled
)

REM Check for TradingView processes
tasklist | find "thinkorswim"
if %errorlevel% equ 0 (
    echo ✅ TradingView process found
) else (
    echo ❌ No TradingView process found
)

echo.
echo To start TradingView with CDP, run: start_tradingview_cdp.bat
echo.
