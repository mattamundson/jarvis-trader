# Kill processes LISTENING on port 8010 only (not client connections to 8010).
function Get-ListenPids8010 {
    Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { $_.OwningProcess } |
        Where-Object { $_ -gt 0 } |
        Sort-Object -Unique
}

$maxKillPasses = 3
for ($i = 0; $i -lt $maxKillPasses; $i++) {
    $pids = @(Get-ListenPids8010)
    if ($pids.Count -eq 0) { break }
    foreach ($p in $pids) {
        Write-Host "Killing PID $p (listener on 8010)"
        $out = & taskkill /F /PID $p 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  taskkill failed (exit $LASTEXITCODE): $out"
        }
    }
    Start-Sleep -Seconds 3
}

$stillListen = @(Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue)
if ($stillListen.Count -gt 0) {
    $blockers = $stillListen | ForEach-Object { $_.OwningProcess } | Where-Object { $_ -gt 0 } | Sort-Object -Unique
    Write-Host "Port 8010 still has LISTEN: PIDs $($blockers -join ', ')"
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8010/health" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) {
            Write-Host "Engine is responding (200). Could not replace listener(s) - use Task Manager (End task) or run this script as Administrator."
            exit 0
        }
    } catch {
        Write-Host "Engine not responding on /health: $($_.Exception.Message)"
    }
    exit 1
}

# Use a rotating client ID (timestamp-based) to avoid IB Gateway client ID conflicts
# IB Gateway holds client IDs for ~60s after disconnect; rotating avoids stale ID issues
$clientId = [int]((Get-Date).ToString("ss")) + 200   # range 200-259, never conflicts with manual tests
$envFile = "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.env"
(Get-Content $envFile) -replace "IBKR_CLIENT_ID=\d+", "IBKR_CLIENT_ID=$clientId" | Set-Content $envFile
Write-Host "Using IBKR client ID: $clientId"

Write-Host "Starting engine..."
$env:PYTHONUTF8 = "1"
Start-Process -FilePath "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "uvicorn", "main:app", "--port", "8010", "--log-level", "warning" `
    -WorkingDirectory "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine" `
    -WindowStyle Hidden

Write-Host "Waiting for engine to start..."
Start-Sleep 15

try {
    $r = Invoke-WebRequest -Uri "http://localhost:8010/health" -UseBasicParsing -TimeoutSec 5
    Write-Host "Engine UP: $($r.StatusCode)"
} catch {
    Write-Host "Engine not responding"
    exit 1
}
