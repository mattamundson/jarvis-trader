$conns = Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) {
    $owningPid = $c.OwningProcess
    Write-Host "Killing PID $owningPid"
    taskkill /F /PID $owningPid 2>$null
}
Start-Sleep 3

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
