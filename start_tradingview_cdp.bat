@echo off
echo Starting TradingView Desktop with CDP debugging...
echo.

REM Set the path to TradingView executable
set TRADINGVIEW_PATH=C:\Program Files\Thinkorswim\thinkorswim.exe

REM Check if TradingView exists
if not exist "%TRADINGVIEW_PATH%" (
    echo TradingView not found at %TRADINGVIEW_PATH%
    echo Please install TradingView Desktop first
    pause
    exit /b 1
)

REM Start TradingView with debugging flags
echo Starting TradingView with CDP debugging...
echo This will enable Chrome DevTools Protocol on port 9222
echo.

"%TRADINGVIEW_PATH%" --remote-debugging-port=9222

echo TradingView started
echo You can access Chrome DevTools at: http://localhost:9222
echo Press any key to exit...
pause
