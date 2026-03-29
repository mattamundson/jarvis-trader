@echo off
title JARVIS TRADER — Startup
color 0A

echo.
echo  ====================================================
echo   JARVIS TRADER — Starting up...
echo  ====================================================
echo.
echo  [1/4] Launching Engine on port 8010...
start "JARVIS ENGINE - Port 8010" cmd /k "title JARVIS ENGINE - Port 8010 && cd /d %~dp0engine && echo JARVIS Engine starting... && .venv\Scripts\python -m uvicorn main:app --port 8010"

echo  [2/4] Launching Dashboard on port 3010...
start "JARVIS DASHBOARD - Port 3010" cmd /k "title JARVIS DASHBOARD - Port 3010 && cd /d %~dp0dashboard && echo JARVIS Dashboard starting... && npm run dev"

echo  [3/4] Launching Health Monitor...
start "JARVIS HEALTH MONITOR" cmd /k "title JARVIS HEALTH MONITOR && cd /d %~dp0engine && echo JARVIS Health Monitor starting... && .venv\Scripts\python health_monitor.py"

echo  [4/4] Opening dashboard in browser after 5 second delay...
timeout /t 5 /nobreak > nul
start http://localhost:3010

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
