# disk-watch.ps1 -- track top disk consumers under home + alert on growth
#
# Snapshots top consumers in home root, AppData/Local, AppData/Roaming.
# Compares to previous snapshot at ~/scripts/.disk-watch-state.json.
# Alerts if any directory grew by >2 GB week-over-week (configurable).

[CmdletBinding()]
param(
    [int]$Top = 15,
    [int]$AlertGrowthMB = 2048,
    [string]$StateFile = "$env:USERPROFILE\scripts\.disk-watch-state.json",
    [string]$OutFile = ""
)

function Get-DirSizeMB {
    param($Path)
    # Streaming enumeration via [System.IO.Directory]; iterative stack avoids the
    # PS pipeline buffering ~1M FileInfo objects on bloated trees (AppData/Local).
    # Skips reparse points to mirror prior junction/symlink exclusion semantics.
    if (-not (Test-Path $Path)) { return 0 }
    [long]$total = 0
    $stack = [System.Collections.Generic.Stack[string]]::new()
    $stack.Push($Path)
    while ($stack.Count -gt 0) {
        $cur = $stack.Pop()
        try {
            foreach ($f in [System.IO.Directory]::EnumerateFiles($cur)) {
                try { $total += [System.IO.FileInfo]::new($f).Length } catch {}
            }
            foreach ($d in [System.IO.Directory]::EnumerateDirectories($cur)) {
                try {
                    $attr = [System.IO.File]::GetAttributes($d)
                    if (-not ($attr -band [System.IO.FileAttributes]::ReparsePoint)) {
                        $stack.Push($d)
                    }
                }
                catch {}
            }
        }
        catch {}
    }
    return [math]::Round($total / 1MB, 1)
}

function Snapshot-Roots {
    param($Roots)
    $entries = @{}
    foreach ($r in $Roots) {
        if (-not (Test-Path $r)) { continue }
        Get-ChildItem -LiteralPath $r -Directory -Force -ErrorAction SilentlyContinue |
            Where-Object {
                # Skip junctions and symlinks (e.g. "Local Settings" -> AppData\Local
                # double-counts disk usage). KEEP cloud-sync reparse points like OneDrive,
                # which set ReparsePoint but no LinkType — those hold real data.
                $_.LinkType -ne 'Junction' -and $_.LinkType -ne 'SymbolicLink'
            } |
            ForEach-Object {
                $sz = Get-DirSizeMB $_.FullName
                $entries[$_.FullName] = $sz
            }
    }
    return $entries
}

$roots = @(
    "C:\Users\mattm",
    "C:\Users\mattm\AppData\Local",
    "C:\Users\mattm\AppData\Roaming"
)

Write-Host "Snapshotting disk usage under $($roots.Count) roots (this may take 1-2 min)..." -ForegroundColor Cyan
$current = Snapshot-Roots -Roots $roots

# Load previous state
$previous = @{}
if (Test-Path $StateFile) {
    try {
        $raw = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
        $raw.entries.PSObject.Properties | ForEach-Object { $previous[$_.Name] = [double]$_.Value }
    }
    catch {}
}

# Top N current
$topEntries = $current.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First $Top
Write-Host ""
Write-Host "=== TOP $Top CONSUMERS ===" -ForegroundColor Cyan
foreach ($e in $topEntries) {
    $sizeStr = if ($e.Value -gt 1024) { "{0:N1} GB" -f ($e.Value / 1024) } else { "{0:N0} MB" -f $e.Value }
    $delta = ""
    if ($previous.ContainsKey($e.Key)) {
        $d = $e.Value - $previous[$e.Key]
        if ([math]::Abs($d) -gt 10) {
            $sign = if ($d -gt 0) { "+" } else { "" }
            $delta = "  (delta {0}{1:N0} MB)" -f $sign, $d
        }
    }
    else {
        $delta = "  (new)"
    }
    Write-Host ("  {0,10}  {1}{2}" -f $sizeStr, $e.Key, $delta)
}

# Growth alerts
$alerts = @()
foreach ($k in $current.Keys) {
    if ($previous.ContainsKey($k)) {
        $delta = $current[$k] - $previous[$k]
        if ($delta -gt $AlertGrowthMB) {
            $alerts += [PSCustomObject]@{
                path        = $k
                growth_mb   = [math]::Round($delta, 1)
                current_mb  = $current[$k]
                previous_mb = $previous[$k]
            }
        }
    }
}

if ($alerts.Count -gt 0) {
    Write-Host ""
    Write-Host "=== GROWTH ALERTS (>$([math]::Round($AlertGrowthMB/1024,1)) GB delta) ===" -ForegroundColor Red
    $alerts | ForEach-Object {
        Write-Host ("  +{0:N0} MB  {1}" -f $_.growth_mb, $_.path) -ForegroundColor Red
    }
}

# Persist current as new state
$state = @{
    timestamp = (Get-Date -Format "o")
    entries   = $current
}
$dir = Split-Path $StateFile -Parent
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
$state | ConvertTo-Json -Depth 5 | Set-Content -Path $StateFile -Encoding UTF8
Write-Host ""
Write-Host "State saved to $StateFile"

if ($OutFile) {
    @{
        snapshot_time = (Get-Date -Format "o")
        top           = $topEntries
        alerts        = $alerts
    } | ConvertTo-Json -Depth 5 | Set-Content -Path $OutFile -Encoding UTF8
}

if ($alerts.Count -gt 0) { exit 2 } else { exit 0 }
