# Kill all processes on port 8010 (handles multiple engine instances)
$conns = Get-NetTCPConnection -LocalPort 8010 -ErrorAction SilentlyContinue
$killed = @()
foreach ($c in $conns) {
    $owningPid = $c.OwningProcess
    if ($owningPid -gt 0 -and $killed -notcontains $owningPid) {
        $killed += $owningPid
        Write-Host "Killing PID $owningPid"
        taskkill /F /PID $owningPid 2>$null
    }
}
Start-Sleep 5

# Use a rotating client ID (timestamp-based) to avoid IB Gateway client ID conflicts
# IB Gateway holds client IDs for ~60s after disconnect; rotating avoids stale ID issues
$clientId = [int]((Get-Date).ToString("ss")) + 200   # range 200-259, never conflicts with manual tests
$envFile = "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.env"
(Get-Content $envFile) -replace "IBKR_CLIENT_ID=\d+", "IBKR_CLIENT_ID=$clientId" | Set-Content $envFile
Write-Host "Using IBKR client ID: $clientId"

# Check if port is free
$check = Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue
if ($check) {
    Write-Host "Port 8010 still busy"
    exit 1
}

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
}
