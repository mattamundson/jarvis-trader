@echo off
setlocal
:: Wait for IB Gateway PAPER port 4002, then reconnect and verify JARVIS.
:: This file contains no credentials; the Python helper reads engine\.env locally.
set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%.."
set "PYTHON=%REPO_ROOT%\engine\.venv\Scripts\python.exe"

echo GATEWAY_KEEPER waiting for IB Gateway paper port 4002...
:wait
%SystemRoot%\System32\ping.exe -n 11 127.0.0.1 >nul
netstat -ano 2>nul | %SystemRoot%\System32\findstr.exe /C:":4002 " | %SystemRoot%\System32\findstr.exe /C:"LISTENING" >nul 2>&1
if errorlevel 1 goto wait

echo GATEWAY_KEEPER detected port 4002; reconnecting the engine...
"%PYTHON%" "%SCRIPT_DIR%gateway_keeper_reconnect.py"
if errorlevel 1 (
    echo GATEWAY_KEEPER failed authoritative paper-health verification.
    exit /b 1
)

echo GATEWAY_KEEPER done. Gateway and engine paper health verified.
exit /b 0
