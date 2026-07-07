$procs = Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess
foreach ($procId in $procs) {
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    Write-Host "Killed PID $procId"
}
Start-Sleep -Seconds 2
$newProc = Start-Process -FilePath "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv\Scripts\python.exe" -ArgumentList @("-m", "uvicorn", "main:app", "--port", "8010", "--host", "0.0.0.0") -WorkingDirectory "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine" -WindowStyle Hidden -PassThru
Write-Host "Engine started PID $($newProc.Id)"
