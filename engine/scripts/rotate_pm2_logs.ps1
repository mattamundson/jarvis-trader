<#
.SYNOPSIS
  PM2 log rotation + retention for jarvis-trader engine / dashboard / master-api.

.DESCRIPTION
  Complements the pm2-logrotate module (which only renames on size and, on Windows,
  overshoots badly under fast write bursts — engine-error.log reached 1.05GB per
  rotated file and produced byte-identical duplicate files on 2026-08-18). This script:

    1. copytruncate-rotates live log files that exceed -MaxSizeMB
       (safe for files PM2 keeps open: copy to name__timestamp.log, then truncate)
    2. gzips rotated (name__timestamp.log) files older than -CompressAfterDays
    3. gzips stale logs (not in the known-active set, untouched for
       -StaleThresholdHours) — e.g. ~/.pm2/logs/jarvis-engine-*.log left over from a
       previous PM2 config that no longer gets written
    4. deletes rotated/compressed files older than -RetainDays
    5. enforces a hard per-directory cap (-DirCapMB) by deleting the oldest
       rotated/compressed files

  Intended to run hourly via Task Scheduler task "JarvisLogRotation".
  Referenced from engine/main.py logging setup as scripts/rotate_pm2_logs.ps1.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File rotate_pm2_logs.ps1
#>
param(
    [int]$MaxSizeMB = 100,
    [int]$RetainDays = 7,
    [int]$CompressAfterDays = 1,
    [int]$StaleThresholdHours = 24,
    [int]$DirCapMB = 1024,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

# ── Log roots (engine + dashboard logs share engine/logs; master-api/ops-console
#    use the default ~/.pm2/logs). Add roots here to extend coverage.
$LogRoots = @(
    'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\logs',
    'C:\Users\mattm\.pm2\logs'
)

# Known-active live logs: never gzipped as "stale", only size-rotated.
# Keyed per root — engine/logs uses bare names (engine-error.log), while
# ~/.pm2/logs uses PM2's <app-name>-out/error.log naming (jarvis-dashboard-*).
$ActiveByRoot = @{
    'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\logs' = @(
        'engine-error.log', 'engine-out.log',
        'dashboard-error.log', 'dashboard-out.log'
    )
    'C:\Users\mattm\.pm2\logs' = @(
        'jarvis-dashboard-error.log', 'jarvis-dashboard-out.log',
        'master-api-error.log', 'master-api-out.log',
        'ops-console-error.log', 'ops-console-out.log',
        'pm2-logrotate-error.log', 'pm2-logrotate-out.log'
    )
}

# Files whose rotation is owned elsewhere (engine RotatingFileHandler: jarvis.log.N)
$SkipPatterns = @('^jarvis\.log(\.\d+)?$')

$AuditLog = 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\logs\rotate_pm2_logs.log'
$Now = Get-Date

function Write-Audit([string]$Message) {
    $line = '{0}  {1}' -f $Now.ToString('yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -LiteralPath $AuditLog -Value $line -Encoding utf8
}

function Get-SizeMB([long]$Bytes) { [math]::Round($Bytes / 1MB, 2) }

function Test-SkipFile([string]$Name) {
    foreach ($pat in $SkipPatterns) { if ($Name -match $pat) { return $true } }
    return $false
}

function Compress-Gzip([string]$Path, [string]$OutPath) {
    # Remove any partial .gz left by a previous failed attempt.
    if (Test-Path -LiteralPath $OutPath) { Remove-Item -LiteralPath $OutPath -Force }
    $in = [System.IO.File]::OpenRead($Path)
    try {
        $out = [System.IO.File]::Create($OutPath)
        try {
            $gz = New-Object System.IO.Compression.GZipStream(
                $out, [System.IO.Compression.CompressionMode]::Compress)
            try { $in.CopyTo($gz) } finally { $gz.Dispose() }
        } finally { $out.Dispose() }
    } finally { $in.Dispose() }
}

function Copy-Truncate([System.IO.FileInfo]$File, [string]$RotatedPath) {
    # Copy, then truncate the original to 0 bytes (share ReadWrite so the owning
    # process can keep its open handle). Lose-at-most-one-line semantics.
    Copy-Item -LiteralPath $File.FullName -Destination $RotatedPath -Force
    $fs = [System.IO.File]::Open(
        $File.FullName,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::ReadWrite)
    try { $fs.SetLength(0) } finally { $fs.Dispose() }
}

# ── 1+2+3+4: per-root pass ────────────────────────────────────────────────────
foreach ($Root in $LogRoots) {
    if (-not (Test-Path -LiteralPath $Root)) { continue }
    $Stamp = $Now.ToString('yyyyMMdd_HHmmss')

    Get-ChildItem -LiteralPath $Root -File | ForEach-Object {
        $f = $_
        $isRotated = $f.Name -match '__'
        $ext = $f.Extension.ToLowerInvariant()

        if ($isRotated) {
            # Rotated file: compress when old enough, delete when past retention.
            # NOTE: use `return` (never `continue`) — inside a ForEach-Object
            # scriptblock nested in the outer `foreach ($Root ...)` statement,
            # `continue` exits the OUTER loop in Windows PowerShell 5.1.
            if ($ext -eq '.gz') { if ($f.LastWriteTime -lt $Now.AddDays(-$RetainDays)) {
                    if ($DryRun) { Write-Audit "[dry] would delete $($f.FullName) (retention)" }
                    else { Remove-Item -LiteralPath $f.FullName -Force; Write-Audit "deleted (retention >$RetainDays d): $($f.FullName)" }
                }
                return
            }
            if ($f.LastWriteTime -lt $Now.AddDays(-$CompressAfterDays)) {
                $gzPath = $f.FullName + '.gz'
                if ($DryRun) { Write-Audit "[dry] would gzip $($f.FullName)" }
                else {
                    try {
                        Compress-Gzip $f.FullName $gzPath
                        Remove-Item -LiteralPath $f.FullName -Force
                        Write-Audit ("gzipped {0} -> {1} ({2} MB -> {3} MB)" -f $f.Name,
                            (Split-Path $gzPath -Leaf), (Get-SizeMB $f.Length),
                            (Get-SizeMB (Get-Item -LiteralPath $gzPath).Length))
                    } catch {
                        if (Test-Path -LiteralPath $gzPath) { Remove-Item -LiteralPath $gzPath -Force }
                        Write-Audit "gzip FAILED for $($f.FullName): $($_.Exception.Message)"
                    }
                }
            }
            elseif ($f.LastWriteTime -lt $Now.AddDays(-$RetainDays)) {
                if ($DryRun) { Write-Audit "[dry] would delete $($f.FullName) (retention)" }
                else { Remove-Item -LiteralPath $f.FullName -Force; Write-Audit "deleted (retention >$RetainDays d): $($f.FullName)" }
            }
            return
        }

        # Live / stale plain log (skip self-managed jarvis.log*)
        if (Test-SkipFile $f.Name) { return }
        if ($f.Name -eq (Split-Path $AuditLog -Leaf)) { return }

        $activeList = $ActiveByRoot[$Root]
        $active = $activeList -contains $f.Name
        $stale = (-not $active) -and ($f.LastWriteTime -lt $Now.AddHours(-$StaleThresholdHours))

        if ($active -or (-not $stale)) {
            if ($f.Length -gt ($MaxSizeMB * 1MB)) {
                $rotated = Join-Path $Root ($f.BaseName + '__' + $Stamp + '.log')
                if ($DryRun) { Write-Audit "[dry] would rotate $($f.Name) ({0} MB)" -f (Get-SizeMB $f.Length) }
                else {
                    try {
                        Copy-Truncate $f $rotated
                        Write-Audit ("rotated {0} ({1} MB) -> {2}" -f $f.Name,
                            (Get-SizeMB $f.Length), (Split-Path $rotated -Leaf))
                    } catch {
                        Write-Audit "rotate FAILED for $($f.FullName): $($_.Exception.Message)"
                    }
                }
            }
        }
        elseif ($f.Length -gt 1MB) {
            # Stale, non-active log: compress it now; retention will delete later.
            $gzPath = $f.FullName + '.gz'
            if ($DryRun) { Write-Audit "[dry] would gzip stale $($f.FullName)" }
            else {
                try {
                    Compress-Gzip $f.FullName $gzPath
                    Remove-Item -LiteralPath $f.FullName -Force
                    Write-Audit ("gzipped stale {0} -> {1} ({2} MB -> {3} MB)" -f $f.Name,
                        (Split-Path $gzPath -Leaf), (Get-SizeMB $f.Length),
                        (Get-SizeMB (Get-Item -LiteralPath $gzPath).Length))
                } catch {
                    if (Test-Path -LiteralPath $gzPath) { Remove-Item -LiteralPath $gzPath -Force }
                    Write-Audit "gzip FAILED for stale $($f.FullName): $($_.Exception.Message)"
                }
            }
        }
    }

    # ── 5: hard dir cap — drop oldest rotated/compressed until under budget ──
    $rotated = Get-ChildItem -LiteralPath $Root -File | Where-Object { $_.Name -match '__|\.gz$' } |
        Sort-Object LastWriteTime
    $total = ($rotated | Measure-Object -Property Length -Sum).Sum
    $capBytes = $DirCapMB * 1MB
    if ($total -gt $capBytes) {
        foreach ($f in $rotated) {
            if ($total -le $capBytes) { break }
            if ($DryRun) { Write-Audit "[dry] would delete $($f.Name) (dir cap $DirCapMB MB)" }
            else { Remove-Item -LiteralPath $f.FullName -Force; Write-Audit "deleted (dir cap $DirCapMB MB): $($f.FullName)" }
            $total -= $f.Length
        }
    }
}

Write-Audit "pass complete (maxSize=${MaxSizeMB}MB retain=${RetainDays}d compressAfter=${CompressAfterDays}d stale=${StaleThresholdHours}h cap=${DirCapMB}MB dry=$DryRun)"
