$conn = Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    foreach ($c in $conn) {
        $pid = $c.OwningProcess
        Write-Host "Killing PID $pid on port 8010"
        taskkill /F /PID $pid 2>$null
        if ($LASTEXITCODE -ne 0) {
            # Try WMI kill
            $proc = Get-WmiObject Win32_Process -Filter "ProcessId=$pid" -ErrorAction SilentlyContinue
            if ($proc) { $proc.Terminate() }
        }
    }
} else {
    Write-Host "No process listening on 8010"
}
Start-Sleep 2
$check = Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue
if ($check) { Write-Host "Still running" } else { Write-Host "Port 8010 is free" }
