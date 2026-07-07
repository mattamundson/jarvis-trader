# Restart engine with fixed is_connected bug
$pids = Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess
foreach ($pid in $pids) {
    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    Write-Host "Killed PID $pid"
}
Start-Sleep -Seconds 3

$proc = Start-Process -FilePath "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv\Scripts\python.exe" `
    -ArgumentList @("-m", "uvicorn", "main:app", "--port", "8010", "--host", "0.0.0.0") `
    -WorkingDirectory "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine" `
    -WindowStyle Hidden -PassThru
Write-Host "Started engine PID $($proc.Id)"
Start-Sleep -Seconds 8
Write-Host "Engine should be ready"
