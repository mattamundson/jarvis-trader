<#
.SYNOPSIS
Installs or updates the recurring JARVIS A-01 runtime snapshot refresh task.

.DESCRIPTION
Registers a limited-user Windows Scheduled Task that runs the safe read-only
snapshot refresh wrapper every N minutes. The task action contains no API keys,
account IDs, or broker credentials.
#>
[CmdletBinding()]
param(
    [string]$TaskName = "Jarvis-A01-RuntimeSnapshotRefresh",
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [int]$EveryMinutes = 5,
    [switch]$RunNow
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($EveryMinutes -lt 1 -or $EveryMinutes -gt 1440) {
    throw "EveryMinutes must be between 1 and 1440."
}

$Wrapper = Join-Path $RepoRoot "scripts\refresh_phase0_runtime_snapshot.ps1"
if (-not (Test-Path -LiteralPath $Wrapper -PathType Leaf)) {
    throw "Refresh wrapper not found: $Wrapper"
}

$PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$ActionArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", ('"{0}"' -f $Wrapper),
    "-RepoRoot", ('"{0}"' -f $RepoRoot)
) -join " "

$TaskRun = ('"{0}" {1}' -f $PowerShell, $ActionArgs)

# Use schtasks for the minute cadence because Windows PowerShell 5.1's
# ScheduledTasks trigger objects are not uniformly writable across hosts.
# This still keeps all quoting inside a script file instead of inline bash.
& schtasks.exe /Create /TN $TaskName /SC MINUTE /MO $EveryMinutes /TR $TaskRun /F | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "schtasks.exe failed to create or update $TaskName with exit code $LASTEXITCODE"
}

& schtasks.exe /Query /TN $TaskName /V /FO LIST | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "schtasks.exe failed to verify $TaskName with exit code $LASTEXITCODE"
}

if ($RunNow) {
    & schtasks.exe /Run /TN $TaskName | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "schtasks.exe failed to start $TaskName with exit code $LASTEXITCODE"
    }
    Write-Host "Started task on demand: $TaskName"
}
