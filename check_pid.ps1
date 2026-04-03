$conn = Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conn) {
    $pid2 = $c.OwningProcess
    Write-Host "Listening PID: $pid2"

    # Try Get-Process
    $proc = Get-Process -Id $pid2 -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "  Process: $($proc.ProcessName) - $($proc.MainModule.FileName)"
    }

    # Try WMI
    $wmiProc = Get-WmiObject Win32_Process -Filter "ProcessId=$pid2" -ErrorAction SilentlyContinue
    if ($wmiProc) {
        Write-Host "  WMI: $($wmiProc.Name) - $($wmiProc.CommandLine)"
    }

    # Try via CIM
    $cimProc = Get-CimInstance Win32_Process -Filter "ProcessId=$pid2" -ErrorAction SilentlyContinue
    if ($cimProc) {
        Write-Host "  CIM: $($cimProc.Name) - $($cimProc.CommandLine)"
    }

    if (-not $proc -and -not $wmiProc -and -not $cimProc) {
        Write-Host "  PID $pid2 not found in any process list!"
        Write-Host "  This may be a kernel-level or zombie connection."
    }
}
