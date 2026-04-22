# ============================================================
# JARVIS API Bridge — Windows Startup Script
# Run this once to install deps, then use it to start/stop
# ============================================================
# Usage (in PowerShell as normal user, NOT system32):
#   cd C:\Users\mattm\workspace\jarvis_api
#   .\deploy\START_WINDOWS.ps1 install   # first time only
#   .\deploy\START_WINDOWS.ps1 start     # start the API
#   .\deploy\START_WINDOWS.ps1 stop      # stop it
#   .\deploy\START_WINDOWS.ps1 status    # check if running
#   .\deploy\START_WINDOWS.ps1 logs      # tail the log

param([string]$Command = "start")

$WorkDir   = "C:\Users\mattm\workspace\jarvis_api"
$LogFile   = "$WorkDir\logs\jarvis_api.log"
$PidFile   = "$WorkDir\logs\jarvis_api.pid"
$Port      = 8020

# Ensure logs folder exists
if (-not (Test-Path "$WorkDir\logs")) {
    New-Item -ItemType Directory -Path "$WorkDir\logs" | Out-Null
}

function Get-ApiPid {
    if (Test-Path $PidFile) {
        $pid = Get-Content $PidFile -Raw
        return $pid.Trim()
    }
    return $null
}

function Test-ApiHealth {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$Port/health" -TimeoutSec 3 -UseBasicParsing
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

switch ($Command) {

    "install" {
        Write-Host "`n[JARVIS] Installing dependencies..." -ForegroundColor Cyan
        python -m pip install fastapi "uvicorn[standard]" yfinance pandas --quiet
        Write-Host "[JARVIS] Install complete." -ForegroundColor Green
        Write-Host "`nRun: .\deploy\START_WINDOWS.ps1 start" -ForegroundColor Yellow
    }

    "start" {
        if (Test-ApiHealth) {
            Write-Host "[JARVIS] API already running on port $Port" -ForegroundColor Green
            exit 0
        }

        Write-Host "[JARVIS] Starting API Bridge on port $Port..." -ForegroundColor Cyan

        $proc = Start-Process -FilePath "python" `
            -ArgumentList "-m uvicorn main:app --host 0.0.0.0 --port $Port" `
            -WorkingDirectory $WorkDir `
            -RedirectStandardOutput $LogFile `
            -RedirectStandardError "$WorkDir\logs\jarvis_api_err.log" `
            -WindowStyle Hidden `
            -PassThru

        $proc.Id | Out-File $PidFile -Encoding ASCII
        Write-Host "[JARVIS] Started with PID $($proc.Id)" -ForegroundColor Green

        # Wait and verify
        Start-Sleep -Seconds 3
        if (Test-ApiHealth) {
            Write-Host "[JARVIS] Health check PASSED — http://localhost:$Port/health" -ForegroundColor Green
        } else {
            Write-Host "[JARVIS] Health check failed — check logs\jarvis_api.log" -ForegroundColor Red
        }
    }

    "stop" {
        $storedPid = Get-ApiPid
        if ($storedPid) {
            try {
                Stop-Process -Id $storedPid -Force
                Remove-Item $PidFile -Force
                Write-Host "[JARVIS] Stopped PID $storedPid" -ForegroundColor Yellow
            } catch {
                Write-Host "[JARVIS] Could not stop PID $storedPid — may already be stopped" -ForegroundColor DarkYellow
            }
        }
        # Also kill any uvicorn on the port just in case
        $netstat = netstat -ano | Select-String ":$Port "
        if ($netstat) {
            $orphanPid = ($netstat -split "\s+")[-1]
            if ($orphanPid -match "^\d+$") {
                Stop-Process -Id $orphanPid -Force -ErrorAction SilentlyContinue
                Write-Host "[JARVIS] Killed orphan process $orphanPid on port $Port" -ForegroundColor Yellow
            }
        }
        Write-Host "[JARVIS] API Bridge stopped." -ForegroundColor Yellow
    }

    "restart" {
        & $PSCommandPath stop
        Start-Sleep -Seconds 2
        & $PSCommandPath start
    }

    "status" {
        if (Test-ApiHealth) {
            $health = Invoke-RestMethod -Uri "http://localhost:$Port/health"
            Write-Host "[JARVIS] ONLINE — $($health.timestamp)" -ForegroundColor Green
            $storedPid = Get-ApiPid
            if ($storedPid) { Write-Host "         PID: $storedPid" -ForegroundColor Cyan }
        } else {
            Write-Host "[JARVIS] OFFLINE — not responding on port $Port" -ForegroundColor Red
        }
    }

    "logs" {
        if (Test-Path $LogFile) {
            Get-Content $LogFile -Wait -Tail 30
        } else {
            Write-Host "No log file yet at $LogFile" -ForegroundColor DarkYellow
        }
    }

    default {
        Write-Host "Usage: .\deploy\START_WINDOWS.ps1 [install|start|stop|restart|status|logs]" -ForegroundColor Cyan
    }
}
