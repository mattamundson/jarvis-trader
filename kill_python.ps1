# Kill all python.exe processes
$procs = Get-Process -Name "python" -ErrorAction SilentlyContinue
foreach ($p in $procs) {
    Write-Host "Killing python PID $($p.Id)"
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep 3
$check = Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue
if ($check) {
    Write-Host "Something still on 8010:"
    $check | ForEach-Object { Write-Host "  PID: $($_.OwningProcess)" }
} else {
    Write-Host "Port 8010 is free"
}
