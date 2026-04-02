$conns = Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) {
    $owningPid = $c.OwningProcess
    $proc = Get-Process -Id $owningPid -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "PID $owningPid - Name: $($proc.ProcessName) - Path: $($proc.MainModule.FileName)"
    } else {
        $wmi = Get-WmiObject Win32_Process -Filter "ProcessId=$owningPid" -ErrorAction SilentlyContinue
        if ($wmi) {
            Write-Host "PID $owningPid - WMI Name: $($wmi.Name) - CommandLine: $($wmi.CommandLine)"
        } else {
            Write-Host "PID $owningPid - not found in Get-Process or WMI"
        }
    }
}
