# Re-runs restart_engine.ps1 in an elevated PowerShell session (UAC prompt).
# Use when taskkill reports Access denied on the process holding port 8010.
$ErrorActionPreference = "Stop"
$repoRoot = $PSScriptRoot
if (-not $repoRoot) { $repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path }
$target = Join-Path $repoRoot "restart_engine.ps1"
if (-not (Test-Path -LiteralPath $target)) {
    Write-Host "Missing: $target"
    exit 1
}
Start-Process -FilePath "powershell.exe" -Verb RunAs -WorkingDirectory $repoRoot `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $target) -Wait
