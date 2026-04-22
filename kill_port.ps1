$conns = Get-NetTCPConnection -LocalPort 8010 -ErrorAction SilentlyContinue
if ($conns) {
    foreach ($c in $conns) {
        Write-Host "Killing PID $($c.OwningProcess) on port 8010"
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    Write-Host "Done killing processes"
} else {
    Write-Host "Port 8010 is clear"
}
