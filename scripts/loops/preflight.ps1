<#
.SYNOPSIS
  Verify a Windows box is ready to run the jarvis-trader loops before you
  schedule anything. Read-only: checks, never changes.

.DESCRIPTION
  Confirms each prerequisite the shipped loops depend on and prints a PASS/WARN/
  FAIL line per check. Run this by hand first (the loop-engineering discipline:
  test before you automate).

  Exit codes:
    0  all required checks PASS (warnings allowed)
    1  one or more required checks FAILED

.EXAMPLE
  pwsh -File scripts\loops\preflight.ps1
#>

[CmdletBinding()]
param(
    [string] $RepoRoot  = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string] $HealthUrl = "http://127.0.0.1:8010/health"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

$failures = 0

function Test-Item {
    param(
        [string] $Name,
        [scriptblock] $Check,   # returns $true / $false
        [switch] $Required,     # a failing required check sets exit 1
        [string] $Hint
    )
    $ok = $false
    try { $ok = & $Check } catch { $ok = $false }
    if ($ok) {
        Write-Host ("  [PASS] {0}" -f $Name)
    }
    elseif ($Required) {
        Write-Host ("  [FAIL] {0}" -f $Name) -ForegroundColor Red
        if ($Hint) { Write-Host ("         -> {0}" -f $Hint) }
        $script:failures++
    }
    else {
        Write-Host ("  [WARN] {0}" -f $Name) -ForegroundColor Yellow
        if ($Hint) { Write-Host ("         -> {0}" -f $Hint) }
    }
}

Write-Host "jarvis-trader loop preflight" -ForegroundColor Cyan
Write-Host "repo: $RepoRoot`n"

Test-Item -Name "Claude Code CLI on PATH (claude)" -Required `
    -Check { [bool](Get-Command claude -ErrorAction SilentlyContinue) } `
    -Hint  "install/login Claude Code so triage-loop.ps1 can run headless"

Test-Item -Name "PowerShell 7 (pwsh) available" -Required `
    -Check { [bool](Get-Command pwsh -ErrorAction SilentlyContinue) } `
    -Hint  "Task Scheduler actions below invoke pwsh.exe"

Test-Item -Name "Engine venv python present" -Required `
    -Check { Test-Path (Join-Path $RepoRoot "engine\.venv\Scripts\python.exe") } `
    -Hint  "morning-brief-loop.ps1 needs engine/.venv (see CLAUDE.md dev quick-start)"

Test-Item -Name "Engine reachable on :8010" `
    -Check {
        try { (Invoke-WebRequest -Uri $HealthUrl -TimeoutSec 5 -UseBasicParsing).StatusCode -eq 200 }
        catch { $false }
    } `
    -Hint  "start the engine before the morning-brief loop runs"

Test-Item -Name "DISCORD_WEBHOOK_URL set (brief delivery)" `
    -Check { -not [string]::IsNullOrWhiteSpace($env:DISCORD_WEBHOOK_URL) } `
    -Hint  "the morning brief posts here; unset = file-only"

Test-Item -Name "JARVIS_LOOP_WEBHOOK set (loop alerts)" `
    -Check { -not [string]::IsNullOrWhiteSpace($env:JARVIS_LOOP_WEBHOOK) } `
    -Hint  "loop failures/heartbeat-stale alerts post here; unset = silent"

Write-Host ""
if ($failures -eq 0) {
    Write-Host "PREFLIGHT OK - safe to run the loops by hand, then schedule." -ForegroundColor Green
    exit 0
}
Write-Host "PREFLIGHT FAILED - $failures required check(s) failed. Fix before scheduling." -ForegroundColor Red
exit 1
