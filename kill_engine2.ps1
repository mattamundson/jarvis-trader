$conns = Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) {
    $owningPid = $c.OwningProcess
    Write-Host "Killing PID $owningPid"
    taskkill /F /PID $owningPid
}
Start-Sleep 3
$check = Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue
if ($check) {
    Write-Host "Still running on 8010"
    $check | ForEach-Object { Write-Host "  PID:" $_.OwningProcess }
} else {
    Write-Host "Port 8010 free"
}
