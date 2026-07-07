# vault-drift-check.ps1 -- weekly health check on the canonical Obsidian vault
#
# Tracks file count, total size, latest .md edit, and existence + size of a
# small set of critical files. Compares against a soft baseline at
# ~/scripts/.vault-drift-state.json. Alerts (non-zero exit) when:
#   - File count drops > 10% from baseline
#   - Total size drops > 30% from baseline
#   - Any critical file is missing or shrinks > 50%
#   - Latest .md edit is > 14 days old (vault appears abandoned)
#
# Exit codes: 0 = healthy, 1 = drift detected, 2 = vault path missing.
# Run via Windows Task Scheduler (added by install-regression-tasks.ps1) and
# wrapped through notify-on-fail.ps1 like the other Phase 7 regression checks.
#
# First run writes baseline + exits 0. Subsequent runs compare and update the
# baseline only on healthy passes (so transient bad states stay flagged until
# resolved).

[CmdletBinding()]
param(
    [string[]]$VaultPath = @(
        "C:\Users\mattm\master-jarvis\second-brain",
        "C:\Users\mattm\OneDrive\Documents\Obsidian Vault"
    ),
    [string]$StateDir = "$env:USERPROFILE\scripts",
    [int]$MaxStaleDays = 14,
    [double]$MinFileCountRatio = 0.9,
    [double]$MinSizeRatio = 0.7,
    [double]$MinCriticalFileSizeRatio = 0.5,
    [switch]$ResetBaseline
)

$ErrorActionPreference = "Stop"

$criticalFilesCommon = @(
    ".obsidian\workspace.json",
    ".obsidian\app.json",
    ".obsidian\core-plugins.json",
    ".obsidian\appearance.json"
)

# Per-vault optional critical files (only checked if they exist at baseline time;
# absence at baseline = not tracked). Lets the same script work for vaults with
# different content shapes.
$criticalFilesOptional = @(
    "Memory.md",
    "Decision-Log.md",
    "Action-Tracker.md",
    "Home.md",
    "CLAUDE.md",
    "Welcome.md"
)

function Slugify($path) {
    # Stable filename-safe id derived from the vault path.
    return ($path -replace '[\\/:*?"<>|]', '_').Trim('_').Replace(' ', '-')
}

$allAlerts = @()
$totalVaults = 0
$missingVaults = 0

foreach ($vault in $VaultPath) {
    $totalVaults++
    Write-Output ""
    Write-Output "==== Vault: $vault ===="

    if (-not (Test-Path $vault)) {
        Write-Output "FAIL: vault path missing"
        $allAlerts += "vault MISSING: $vault"
        $missingVaults++
        continue
    }

    $stateFile = Join-Path $StateDir (".vault-drift-state-{0}.json" -f (Slugify $vault))

    $now = Get-Date
    $files = Get-ChildItem $vault -Recurse -Force -File -ErrorAction SilentlyContinue
    $mdFiles = $files | Where-Object { $_.Extension -eq ".md" }
    $totalBytes = ($files | Measure-Object -Sum Length).Sum
    $latestMd = ($mdFiles | Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime
    $daysSinceMd = if ($latestMd) { [math]::Round(($now - $latestMd).TotalDays, 1) } else { 9999 }

    $criticalToTrack = $criticalFilesCommon + ($criticalFilesOptional | Where-Object { Test-Path (Join-Path $vault $_) })

    $criticalSnapshot = @{}
    foreach ($f in $criticalToTrack) {
        $p = Join-Path $vault $f
        $criticalSnapshot[$f] = if (Test-Path $p) { (Get-Item $p).Length } else { 0 }
    }

    $current = [pscustomobject]@{
        timestamp      = $now.ToString("o")
        vault          = $vault
        file_count     = $files.Count
        md_count       = $mdFiles.Count
        total_bytes    = $totalBytes
        latest_md_edit = if ($latestMd) { $latestMd.ToString("o") } else { $null }
        days_since_md  = $daysSinceMd
        critical_sizes = $criticalSnapshot
    }

    if ($ResetBaseline -or -not (Test-Path $stateFile)) {
        $current | ConvertTo-Json -Depth 5 | Set-Content $stateFile -Encoding UTF8
        Write-Output "BASELINE: wrote first state to $stateFile"
        Write-Output "  files=$($current.file_count)  md=$($current.md_count)  size_MB=$([math]::Round($totalBytes/1MB,2))  days_since_md=$daysSinceMd"
        continue
    }

    $baseline = Get-Content $stateFile -Raw | ConvertFrom-Json
    $alerts = @()

    if ($current.file_count -lt $baseline.file_count * $MinFileCountRatio) {
        $alerts += "[$vault] file_count dropped: was=$($baseline.file_count) now=$($current.file_count) (min ratio $MinFileCountRatio)"
    }
    if ($current.total_bytes -lt $baseline.total_bytes * $MinSizeRatio) {
        $alerts += "[$vault] total_bytes dropped: was=$($baseline.total_bytes) now=$($current.total_bytes) (min ratio $MinSizeRatio)"
    }
    if ($daysSinceMd -gt $MaxStaleDays) {
        $alerts += "[$vault] vault stale: latest .md edit is $daysSinceMd days old (threshold $MaxStaleDays)"
    }
    foreach ($f in $criticalToTrack) {
        $wasSize = [int64]$baseline.critical_sizes.$f
        $nowSize = [int64]$criticalSnapshot[$f]
        if ($nowSize -eq 0 -and $wasSize -gt 0) {
            $alerts += "[$vault] critical file MISSING: $f (was ${wasSize}B)"
        }
        elseif ($wasSize -gt 0 -and $nowSize -lt $wasSize * $MinCriticalFileSizeRatio) {
            $alerts += "[$vault] critical file shrunk: $f was=${wasSize}B now=${nowSize}B"
        }
    }

    Write-Output "  files=$($current.file_count) (was $($baseline.file_count))"
    Write-Output "  md=$($current.md_count) (was $($baseline.md_count))"
    Write-Output "  size_MB=$([math]::Round($totalBytes/1MB,2)) (was $([math]::Round([int64]$baseline.total_bytes/1MB,2)))"
    Write-Output "  days_since_md=$daysSinceMd (threshold $MaxStaleDays)"

    if ($alerts.Count -eq 0) {
        Write-Output "  OK: no drift; updating baseline"
        $current | ConvertTo-Json -Depth 5 | Set-Content $stateFile -Encoding UTF8
    }
    else {
        $allAlerts += $alerts
    }
}

Write-Output ""
Write-Output "==== Summary ===="
Write-Output "Vaults checked: $totalVaults  missing: $missingVaults  alerts: $($allAlerts.Count)"

if ($allAlerts.Count -eq 0 -and $missingVaults -eq 0) {
    exit 0
}

Write-Output ""
Write-Output "ISSUES:"
foreach ($a in $allAlerts) { Write-Output "  - $a" }
Write-Output ""
Write-Output "Baseline NOT updated for vaults with drift. Re-run with -ResetBaseline after resolving."
if ($missingVaults -gt 0) { exit 2 } else { exit 1 }
