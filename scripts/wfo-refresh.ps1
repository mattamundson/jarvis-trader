# wfo-refresh.ps1 — Monthly WFO re-run for active production instruments.
#
# Runs the champion walk-forward scripts for MES (rank11) and MGC (rank4)
# to detect regime drift before it affects live paper P&L.
#
# Output is logged to engine/backtest/wfo-refresh-logs/YYYY-MM-DD.log.
# Exit code 0 = all verdicts still PASS; 1 = at least one changed to FAIL.
#
# Usage (ad-hoc):
#   pwsh -NoProfile -File scripts/wfo-refresh.ps1
#
# Scheduled via scripts/install-wfo-refresh-task.ps1.

$ErrorActionPreference = "Stop"

$repoRoot  = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$engineDir = Join-Path $repoRoot "engine"
$python    = Join-Path $engineDir ".venv\Scripts\python.exe"
$logDir    = Join-Path $engineDir "backtest\wfo-refresh-logs"
$dateStamp = (Get-Date -Format "yyyy-MM-dd")
$logFile   = Join-Path $logDir "$dateStamp.log"

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

function Write-Log {
    param([string]$Msg)
    $ts = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    $line = "[$ts] $Msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

if (-not (Test-Path $python)) {
    Write-Log "ERROR: Python venv not found at $python"
    exit 1
}

Write-Log "=== WFO REFRESH START ==="
Write-Log "Repo : $repoRoot"
Write-Log "Log  : $logFile"

$scripts = @(
    @{ Name = "MES rank11 (SMA 60/200)"; File = "run_mes_trend_rank11.py" },
    @{ Name = "MGC rank4 (SMA 50/120)";  File = "run_mgc_trend_rank4.py"  }
)

$anyFail = $false

foreach ($s in $scripts) {
    $scriptPath = Join-Path $engineDir "backtest\$($s.File)"
    if (-not (Test-Path $scriptPath)) {
        Write-Log "SKIP $($s.Name) — script not found: $scriptPath"
        continue
    }
    Write-Log "--- Running $($s.Name) ---"
    try {
        $output = & $python $scriptPath 2>&1
        foreach ($line in $output) { Write-Log "  $line" }
        # Detect FAIL verdict in output
        $failLine = $output | Where-Object { $_ -match "GATE v2 VERDICT: FAIL" }
        if ($failLine) {
            Write-Log "ALERT: $($s.Name) VERDICT CHANGED TO FAIL — review and update paper config"
            $anyFail = $true
        } else {
            Write-Log "OK: $($s.Name) verdict still PASS"
        }
    } catch {
        Write-Log "ERROR running $($s.Name): $_"
        $anyFail = $true
    }
}

# Family-wide BH-FDR across the whole gate-v2 verdict set, and append a
# timestamped robust_edge record to the history ledger so drift is tracked
# across refreshes. Diagnostic only -- a zero-survivor result is the honest
# norm with few OOS windows and does NOT flip the PASS/FAIL exit code.
Write-Log "--- Running family-wide BH-FDR (robust_edge ledger) ---"
Push-Location $engineDir
try {
    $fdrOut = & $python -m backtest.family_fdr --history 2>&1
    foreach ($line in $fdrOut) { Write-Log "  $line" }
    $robustLine = $fdrOut | Where-Object { $_ -match "\[history\] n_robust_edge=" }
    if ($robustLine) {
        Write-Log "FDR: $robustLine"
    } else {
        Write-Log "FDR: family-fdr ran (no history line captured -- check log)"
    }
} catch {
    # Diagnostic step must never break the refresh task's PASS/FAIL signal.
    Write-Log "WARN: family-fdr step errored (non-fatal): $_"
} finally {
    Pop-Location
}

Write-Log "=== WFO REFRESH COMPLETE ==="
if ($anyFail) {
    Write-Log "RESULT: one or more verdicts FAILED — check log and update paper config"
    exit 1
} else {
    Write-Log "RESULT: all verdicts PASS — no action needed"
    exit 0
}
