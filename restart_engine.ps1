
# If the JarvisEngine scheduled task is registered, use it for clean stop/start.
$taskName = "JarvisEngine"
$taskExists = (schtasks /query /tn $taskName 2>$null) -match $taskName
if ($taskExists) {
    Write-Host "Stopping JarvisEngine task..."
    schtasks /end /tn $taskName 2>$null | Out-Null
    Start-Sleep 3
}

# Kill processes LISTENING on port 8010 only
function Get-ListenPids8010 {
    Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { $_.OwningProcess } |
        Where-Object { $_ -gt 0 } |
        Sort-Object -Unique
}

# WSL2 guard: netstat sometimes reports WSL2 port-forwarding entries with
# PIDs that don't exist as real Windows processes.  Cross-reference netstat
# against the live Windows process list and kill only the intersection.
function Kill-WSL2SafePids8010 {
    $netstatPids = (netstat -ano 2>$null | Select-String ":\b8010\b\s" | ForEach-Object {
        ($_ -split '\s+')[-1]
    }) | Sort-Object -Unique | Where-Object { $_ -match '^\d+$' }

    if (-not $netstatPids) { return }

    # Match any live Windows PID (not only python*) so listeners under other hosts still resolve.
    $winPids = (Get-Process -ErrorAction SilentlyContinue).Id
    $toKill = $netstatPids | Where-Object { $winPids -contains [int]$_ }

    foreach ($p in $toKill) {
        Write-Host "Killing netstat PID $p (WSL2-safe check)"
        taskkill /PID $p /F 2>$null | Out-Null
    }
}

$repoRoot = "C:\Users\mattm\ThinkorSwim\jarvis-trader"
$pythonExe = Join-Path $repoRoot "engine\.venv\Scripts\python.exe"
$envFile = Join-Path $repoRoot "engine\.env"

$maxKillPasses = 3
for ($i = 0; $i -lt $maxKillPasses; $i++) {
    $pids = @(Get-ListenPids8010)
    if ($pids.Count -eq 0) { break }
    foreach ($p in $pids) {
        Write-Host "Killing PID $p (listener on 8010)"
        $out = & taskkill /F /PID $p 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host " taskkill failed (exit $LASTEXITCODE): $out"
        }
    }
    # Secondary WSL2-safe pass: kills any python PIDs that netstat sees on
    # port 8010 but Get-NetTCPConnection may have missed (port-forwarding).
    Kill-WSL2SafePids8010
    Start-Sleep -Seconds 3
}

$stillListen = @(Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue)
if ($stillListen.Count -gt 0) {
    $blockers = $stillListen | ForEach-Object { $_.OwningProcess } | Where-Object { $_ -gt 0 } | Sort-Object -Unique
    Write-Host "Port 8010 still has LISTEN: PIDs $($blockers -join ', ')"
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8010/health" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) {
            Write-Host "ENGINE RESTART FAILED: Old process still running. Run as Administrator or use Task Manager to kill python.exe started earliest today."
            Write-Host "  → Right-click Task Manager → Run as Administrator → find python.exe → End Task → re-run this script."
            exit 1
        }
    } catch {
        Write-Host "Engine not responding on /health: $($_.Exception.Message)"
    }
    exit 1
}

# Rotate IBKR client ID
$clientId = [int]((Get-Date).ToString("ss")) + 200
(Get-Content $envFile) -replace "IBKR_CLIENT_ID=\d+", "IBKR_CLIENT_ID=$clientId" | Set-Content $envFile
Write-Host "Using IBKR client ID: $clientId"

Write-Host "Starting engine..."
$env:PYTHONUTF8 = "1"

# Load .env into current session so Start-Process inherits correct values.
# This overrides any stale system env vars (e.g., POLYGON_API_KEY=test, API_KEY=test-key).
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^([A-Z][A-Z0-9_]*)=(.*)$') {
            $k = $matches[1]; $v = $matches[2].Trim('"').Trim("'")
            Set-Item -Path "Env:\$k" -Value $v
        }
    }
}

if ($taskExists) {
    Write-Host "Starting via Task Scheduler (no admin required)..."
    schtasks /run /tn $taskName
} else {
    Start-Process -FilePath $pythonExe `
        -ArgumentList "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010", "--log-level", "warning" `
        -WorkingDirectory (Join-Path $repoRoot "engine") `
        -WindowStyle Hidden
}

Write-Host "Waiting for engine to start..."
Start-Sleep 15

try {
    $r = Invoke-WebRequest -Uri "http://localhost:8010/health" -UseBasicParsing -TimeoutSec 5
    Write-Host "Engine UP: $($r.StatusCode)"
} catch {
    Write-Host "Engine not responding"
    exit 1
}