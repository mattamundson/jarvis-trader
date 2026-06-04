<#
.SYNOPSIS
    One-command revert of the ALLOW_PAPER_SIMULATED_ORDERS=True flip.

.DESCRIPTION
    Restores engine/.env to the pre-flip state:
      - ALLOW_PAPER_SIMULATED_ORDERS  -> False  (approved trades go back to
        SIMULATED fills instead of real IB paper orders)
      - removes the READINESS_EDGE_MODE=wfo_plus_fidelity line we added
        (with the flag off, wfo_plus_fidelity would force readiness to NO-GO,
        since no real fills exist -- so it must come out on revert).
    Then restarts the engine (unless -NoRestart) so the change takes effect.

    Safe to re-run: idempotent. Does nothing destructive beyond these two
    config lines. Kill switch / LIVE_TRADING_ENABLED / REQUIRE_HUMAN_APPROVAL
    are never touched. Edits in place with UTF-8 (no BOM) to preserve any
    non-ASCII bytes elsewhere in the file.

.PARAMETER NoRestart
    Revert the config only; do NOT restart the engine. (You then restart
    manually with .\restart_engine.ps1 when ready.)

.EXAMPLE
    .\revert-paper-sim-orders.ps1
    .\revert-paper-sim-orders.ps1 -NoRestart
#>
[CmdletBinding()]
param(
    [switch]$NoRestart
)

$ErrorActionPreference = 'Stop'
$envFile = Join-Path $PSScriptRoot 'engine\.env'

if (-not (Test-Path $envFile)) {
    Write-Error "engine\.env not found at $envFile"
    exit 1
}

# Read preserving UTF-8; rewrite without BOM so python-dotenv stays happy.
$enc   = New-Object System.Text.UTF8Encoding($false)
$lines = [System.IO.File]::ReadAllLines($envFile)

$flagFound = $false
$out = New-Object System.Collections.Generic.List[string]
foreach ($line in $lines) {
    if ($line -match '^\s*ALLOW_PAPER_SIMULATED_ORDERS\s*=') {
        $out.Add('ALLOW_PAPER_SIMULATED_ORDERS=False')
        $flagFound = $true
        continue
    }
    # Drop the readiness-edge-mode line we added during the flip.
    if ($line -match '^\s*READINESS_EDGE_MODE\s*=\s*wfo_plus_fidelity\s*$') {
        continue
    }
    $out.Add($line)
}

if (-not $flagFound) {
    Write-Warning "ALLOW_PAPER_SIMULATED_ORDERS line not found -- nothing changed."
} else {
    [System.IO.File]::WriteAllLines($envFile, $out, $enc)
    Write-Host "[revert] engine\.env reverted:" -ForegroundColor Green
}

# Echo the resulting state of both keys.
Select-String -Path $envFile -Pattern '^(ALLOW_PAPER_SIMULATED_ORDERS|READINESS_EDGE_MODE)' |
    ForEach-Object { "  $($_.Line)" }
if (-not (Select-String -Path $envFile -Pattern '^READINESS_EDGE_MODE=' -Quiet)) {
    Write-Host "  READINESS_EDGE_MODE removed (defaults to paper_accrual)" -ForegroundColor DarkGray
}

if ($NoRestart) {
    Write-Host "`n[revert] -NoRestart set. Run .\restart_engine.ps1 to apply." -ForegroundColor Yellow
    exit 0
}

Write-Host "`n[revert] Restarting engine to apply (~4 min)..." -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'restart_engine.ps1')
