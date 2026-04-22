# Register JARVIS Engine as a Windows Task Scheduler task.
# Run ONCE (as Administrator) to set up. After this, restart_engine.ps1 works
# without admin because the process runs as the current user, not as SYSTEM.
#
# Usage:
#   Right-click PowerShell → Run as Administrator
#   cd C:\Users\mattm\ThinkorSwim\jarvis-trader
#   .\setup_engine_task.ps1
#
# After setup:
#   Start:  schtasks /run /tn "JarvisEngine"
#   Stop:   schtasks /end /tn "JarvisEngine"
#   Status: schtasks /query /tn "JarvisEngine"

$taskName  = "JarvisEngine"
$repoRoot  = "C:\Users\mattm\ThinkorSwim\jarvis-trader"
$python    = "$repoRoot\engine\.venv\Scripts\python.exe"
$args      = "-m uvicorn main:app --host 0.0.0.0 --port 8010 --log-level warning"

# Remove existing task if present
schtasks /delete /tn $taskName /f 2>$null | Out-Null

# Create task — runs as current user (no elevation), on demand only
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>JARVIS Trader Engine (FastAPI, port 8010)</Description>
  </RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <UserId>$env:USERDOMAIN\$env:USERNAME</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>5</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$python</Command>
      <Arguments>$args</Arguments>
      <WorkingDirectory>$repoRoot\engine</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

$tmpXml = "$env:TEMP\jarvis-engine-task.xml"
$xml | Out-File -FilePath $tmpXml -Encoding Unicode
schtasks /create /tn $taskName /xml $tmpXml /f
Remove-Item $tmpXml

Write-Host ""
Write-Host "Task registered: $taskName"
Write-Host "Start engine:  schtasks /run /tn JarvisEngine"
Write-Host "Stop engine:   schtasks /end /tn JarvisEngine"
Write-Host ""
Write-Host "Now run restart_engine.ps1 to start the engine via Task Scheduler."
