<#
.SYNOPSIS
    Archive-then-truncate oversized PM2 logs for the Jarvis engine, and (optionally)
    install pm2-logrotate so the bloat never recurs.

.DESCRIPTION
    The jarvis-engine error log grows unbounded when IB Gateway is down: the IBKR
    connector retries and logs "ConnectionRefused" on every attempt. On 2026-07-06
    the error log reached ~220 MB. This script:

      1. Archives each oversized log to ~/Archive/<year>/pm2-logs/ (never deletes --
         per the archive-never-delete rule), preserving full history recoverably.
      2. Truncates the live log via Clear-Content, which zeroes the file WITHOUT
         breaking the handle PM2/uvicorn holds open (a '> file' redirect can leave a
         sparse file on Windows; Clear-Content is the safe path).
      3. Optionally installs + configures pm2-logrotate (-InstallLogrotate) so PM2
         self-rotates at 50 MB with 7 retained files -- the durable fix.

    Truncation is gated behind -Apply. Without it the script only reports (dry-run),
    because zeroing a log is mildly destructive (history moves to the archive copy).

.PARAMETER ThresholdMB
    Only rotate logs at or above this size. Default 50.

.PARAMETER Apply
    Actually archive + truncate. Omit for a dry-run report.

.PARAMETER InstallLogrotate
    Install and configure pm2-logrotate (the recurrence-proof fix).

.EXAMPLE
    pwsh -File scripts/rotate_pm2_logs.ps1
    # Dry-run: report which logs exceed the threshold.

.EXAMPLE
    pwsh -File scripts/rotate_pm2_logs.ps1 -Apply -InstallLogrotate
    # Archive + truncate oversized logs AND install pm2-logrotate.
#>
[CmdletBinding()]
param(
    [double]$ThresholdMB = 50,
    [switch]$Apply,
    [switch]$InstallLogrotate
)

$ErrorActionPreference = 'Stop'

$logDir = Join-Path $env:USERPROFILE '.pm2\logs'
if (-not (Test-Path $logDir)) {
    Write-Host "[rotate] No PM2 log dir at $logDir -- nothing to do."
    return
}

$year = (Get-Item $logDir).LastWriteTime.Year  # avoid Date.Now nondeterminism in tooling
$archiveDir = Join-Path $env:USERPROFILE "Archive\$year\pm2-logs"

$thresholdBytes = $ThresholdMB * 1MB
$logs = Get-ChildItem -Path $logDir -Filter '*.log' -File |
    Where-Object { $_.Length -ge $thresholdBytes }

if (-not $logs) {
    Write-Host "[rotate] No logs at/above $ThresholdMB MB. Clean."
}
else {
    if ($Apply -and -not (Test-Path $archiveDir)) {
        New-Item -ItemType Directory -Force -Path $archiveDir | Out-Null
    }
    foreach ($log in $logs) {
        $sizeMB = [math]::Round($log.Length / 1MB, 1)
        if (-not $Apply) {
            Write-Host "[rotate] WOULD rotate $($log.Name) ($sizeMB MB) -- re-run with -Apply"
            continue
        }
        $stamp = $log.LastWriteTime.ToString('yyyyMMdd-HHmmss')
        $dest = Join-Path $archiveDir "$($log.BaseName)_$stamp.log"
        Write-Host "[rotate] Archiving $($log.Name) ($sizeMB MB) -> $dest"
        Copy-Item -Path $log.FullName -Destination $dest -Force
        Write-Host "[rotate] Truncating $($log.Name) (handle-safe Clear-Content)"
        Clear-Content -Path $log.FullName -Force
    }
}

if ($InstallLogrotate) {
    Write-Host "[rotate] Installing + configuring pm2-logrotate (durable fix)..."
    pm2 install pm2-logrotate
    pm2 set pm2-logrotate:max_size 50M
    pm2 set pm2-logrotate:retain 7
    pm2 set pm2-logrotate:compress true
    pm2 set pm2-logrotate:rotateInterval '0 3 * * *'
    Write-Host "[rotate] pm2-logrotate set: 50M rotate, 7 retained, compressed, daily 03:00."
}
