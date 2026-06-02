# health-snapshot.ps1 -- consolidated weekly health report
#
# Runs all 5 workers under ~/scripts/ and produces ONE summary report.
# Designed for a single weekly cron call (or interactive Sunday-morning run).
# Each worker exits with non-zero on HIGH findings; this script aggregates.
#
# Usage:
#   .\health-snapshot.ps1                # console output only
#   .\health-snapshot.ps1 -OutDir path   # also writes JSON dumps + summary.md
#
# Workers run sequentially (each may take 30-90 seconds). Total ~5 minutes.

[CmdletBinding()]
param(
    [string]$OutDir = ""
)

$ErrorActionPreference = "Continue"
$started = Get-Date

$ScriptDir = $PSScriptRoot
$Workers = @(
    @{
        Name     = "tool-health"
        Path     = Join-Path $ScriptDir "tool-health.ps1"
        Args     = @()
        TimeoutS = 60
    },
    @{
        Name     = "scan-credentials"
        Path     = Join-Path $ScriptDir "scan-credentials.ps1"
        Args     = @("-Quiet")
        TimeoutS = 300
    },
    @{
        Name     = "scan-uncommitted"
        Path     = Join-Path $ScriptDir "scan-uncommitted.ps1"
        Args     = @()
        TimeoutS = 180
    },
    @{
        Name     = "repo-remote-check"
        Path     = Join-Path $ScriptDir "repo-remote-check.ps1"
        Args     = @()
        TimeoutS = 600
    },
    @{
        Name     = "disk-watch"
        Path     = Join-Path $ScriptDir "disk-watch.ps1"
        Args     = @("-Top", "15")
        TimeoutS = 300
    }
)

function Step($msg, [string]$color = "Cyan") {
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts] $msg" -ForegroundColor $color
}

if ($OutDir -and -not (Test-Path $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

$results = @()

foreach ($w in $Workers) {
    if (-not (Test-Path $w.Path)) {
        Step "SKIP $($w.Name): not found at $($w.Path)" "Yellow"
        $results += [PSCustomObject]@{
            name         = $w.Name
            status       = "SKIPPED"
            exit_code    = $null
            elapsed_s    = 0
            output_lines = 0
        }
        continue
    }

    Step "Running $($w.Name) (timeout $($w.TimeoutS)s)..."
    $tStart = Get-Date

    $tempOut = if ($OutDir) { Join-Path $OutDir "$($w.Name).log" } else { [System.IO.Path]::GetTempFileName() }

    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $w.Path) + $w.Args
    $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $argList `
        -RedirectStandardOutput $tempOut -PassThru -NoNewWindow

    if ($proc.WaitForExit($w.TimeoutS * 1000)) {
        $elapsed = ((Get-Date) - $tStart).TotalSeconds
        $exitCode = $proc.ExitCode
        $lines = (Get-Content $tempOut -ErrorAction SilentlyContinue).Count

        $statusLabel = switch ($exitCode) {
            0 { "OK" }
            2 { "ALERT" }
            default { "ERROR" }
        }
        $color = switch ($exitCode) { 0 { "Green" } 2 { "Red" } default { "Yellow" } }
        Step ("  $statusLabel exit=$exitCode lines=$lines elapsed=$([math]::Round($elapsed,1))s") $color
    }
    else {
        Step "  TIMEOUT after $($w.TimeoutS)s -- killing" "Red"
        try { $proc.Kill() } catch {}
        $statusLabel = "TIMEOUT"
        $exitCode = $null
        $elapsed = $w.TimeoutS
        $lines = (Get-Content $tempOut -ErrorAction SilentlyContinue).Count
    }

    $results += [PSCustomObject]@{
        name         = $w.Name
        status       = $statusLabel
        exit_code    = $exitCode
        elapsed_s    = [math]::Round($elapsed, 1)
        output_lines = $lines
    }

    if (-not $OutDir -and (Test-Path $tempOut)) {
        Remove-Item -LiteralPath $tempOut -Force -ErrorAction SilentlyContinue
    }
}

# ============================================================
# Summary
# ============================================================

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "HEALTH SNAPSHOT SUMMARY" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
$results | Format-Table -AutoSize | Out-String | Write-Host

$alerts = $results | Where-Object status -In @("ALERT", "TIMEOUT", "ERROR")
$totalElapsed = ((Get-Date) - $started).TotalMinutes
Write-Host ("Total elapsed: {0:N1} minutes" -f $totalElapsed)
Write-Host ""

if ($OutDir) {
    $summaryFile = Join-Path $OutDir "summary.md"
    $md = @()
    $md += "# Health Snapshot $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    $md += ""
    $md += "| Worker | Status | Exit | Elapsed (s) | Output lines |"
    $md += "|--------|--------|------|-------------|--------------|"
    foreach ($r in $results) {
        $md += "| $($r.name) | $($r.status) | $($r.exit_code) | $($r.elapsed_s) | $($r.output_lines) |"
    }
    $md += ""
    $md += "Total elapsed: $([math]::Round($totalElapsed, 1)) minutes"
    if ($alerts) {
        $md += ""
        $md += "## Alerts"
        foreach ($a in $alerts) {
            $md += "- **$($a.name)** ($($a.status)) -- see ``$($a.name).log``"
        }
    }
    $md -join "`n" | Set-Content -Path $summaryFile -Encoding UTF8
    Write-Host "Summary: $summaryFile"
}

if ($alerts) {
    Write-Host ("ALERTS: {0} workers reported issues" -f $alerts.Count) -ForegroundColor Red
    $alerts | ForEach-Object { Write-Host "  - $($_.name) ($($_.status))" -ForegroundColor Red }
    exit 2
}
else {
    Write-Host "All workers OK." -ForegroundColor Green
    exit 0
}
