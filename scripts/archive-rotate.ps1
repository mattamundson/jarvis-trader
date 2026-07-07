# archive-rotate.ps1 -- monthly inbox + loose-files rotation
#
# Implements the convention from ~/.claude/rules/cleanup-and-archive.md:
#   1. Move items from ~/Inbox/ older than $InboxAgeDays into
#      ~/Archive/<current-year>/inbox-rotation/.
#   2. Delete items in ~/.archive/loose-files/ older than $ArchiveAgeDays.
#
# Default mode is -DryRun. Pass -Execute to actually move/delete.
#
# Pillar protection: refuses to operate if ~/Inbox/ contains a symlink
# pointing into the 5 active-stack pillars (.claude, ThinkorSwim/jarvis-trader,
# .thinkorswim, second-brain, career-ops).

[CmdletBinding()]
param(
    [switch]$Execute,
    [int]$InboxAgeDays = 30,
    [int]$ArchiveAgeDays = 365,
    # Extra purge roots — additional cold-storage trees that follow the same
    # 12-month-dwell convention as ~/.archive/loose-files/. Defaults cover
    # D:\.archive\* parallel structure created by the 2026-05-04 D-drive archive
    # work. Pass an empty array to disable.
    [string[]]$ExtraPurgeRoots = @("D:\.archive\loose-files", "D:\.archive\2026", "D:\.archive\2027", "D:\.archive\2028")
)

$DryRun = -not $Execute

$InboxDir = "C:\Users\mattm\Inbox"
$ArchiveDir = "C:\Users\mattm\Archive"
$LooseDir = "C:\Users\mattm\.archive\loose-files"
$Year = (Get-Date).Year
$YearArchiveDir = Join-Path $ArchiveDir "$Year\inbox-rotation"

$Pillars = @(
    "C:\Users\mattm\.claude",
    "C:\Users\mattm\ThinkorSwim\jarvis-trader",
    "C:\Users\mattm\.thinkorswim",
    "C:\Users\mattm\second-brain",
    "C:\Users\mattm\career-ops"
)

function Step($msg, [string]$color = "Cyan") {
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts] $msg" -ForegroundColor $color
}

function Resolve-IfSymlink($Path) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if ($null -eq $item) { return $null }
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        return $item.Target
    }
    return $null
}

Step "archive-rotate.ps1 starting (mode: $(if ($DryRun) {'DRY-RUN'} else {'EXECUTE'}))"
Step "  Inbox-age cutoff:   $InboxAgeDays days"
Step "  Archive-age cutoff: $ArchiveAgeDays days"

# ============================================================
# Pillar protection
# ============================================================

if (Test-Path $InboxDir) {
    Step "Checking ~/Inbox/ for pillar-pointing symlinks..."
    $unsafe = $false
    Get-ChildItem -LiteralPath $InboxDir -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $target = Resolve-IfSymlink $_.FullName
        if ($target) {
            foreach ($pillar in $Pillars) {
                if ($target -like "$pillar*") {
                    Write-Host "REFUSING TO RUN: $($_.FullName) is a symlink to active-stack pillar $pillar" -ForegroundColor Red
                    $unsafe = $true
                }
            }
        }
    }
    if ($unsafe) { exit 1 }
}

# ============================================================
# 1. Inbox -> Archive
# ============================================================

$inboxMoved = 0
$inboxSkipped = 0

if (-not (Test-Path $InboxDir)) {
    Step "~/Inbox/ does not exist; nothing to rotate from there." "Yellow"
}
else {
    Step "Scanning ~/Inbox/ for items older than $InboxAgeDays days..."
    $cutoff = (Get-Date).AddDays(-$InboxAgeDays)

    if (-not $DryRun -and -not (Test-Path $YearArchiveDir)) {
        New-Item -ItemType Directory -Path $YearArchiveDir -Force | Out-Null
        Step "  Created target dir: $YearArchiveDir" "Green"
    }

    Get-ChildItem -LiteralPath $InboxDir -Force -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -notin @('.gitkeep', '.git') -and
            $_.LastWriteTime -lt $cutoff
        } |
        ForEach-Object {
            $dest = Join-Path $YearArchiveDir $_.Name
            if ($DryRun) {
                Write-Host "  [DRY] move $($_.FullName) -> $dest" -ForegroundColor Yellow
            }
            else {
                try {
                    Move-Item -LiteralPath $_.FullName -Destination $dest -Force -ErrorAction Stop
                    Write-Host "  [OK]  moved $($_.Name)" -ForegroundColor Green
                    $inboxMoved++
                }
                catch {
                    Write-Host "  [ERR] $($_.Name) -- $($_.Exception.Message)" -ForegroundColor Red
                    $inboxSkipped++
                }
            }
        }
}

# ============================================================
# 2a. Loose-files purge (~/.archive/loose-files/ — recursive, file-level)
# ============================================================

$loosePurged = 0
$loosePurgeSkipped = 0
$cutoff = (Get-Date).AddDays(-$ArchiveAgeDays)

if (-not (Test-Path $LooseDir)) {
    Step "$LooseDir does not exist; skipping loose-files purge." "Yellow"
}
else {
    Step "Scanning $LooseDir for entries older than $ArchiveAgeDays days (file-level)..."

    Get-ChildItem -LiteralPath $LooseDir -Force -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $cutoff } |
        ForEach-Object {
            if ($DryRun) {
                Write-Host "  [DRY] delete $($_.FullName)" -ForegroundColor Yellow
            }
            else {
                try {
                    Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
                    Write-Host "  [OK]  deleted $($_.FullName)" -ForegroundColor Green
                    $loosePurged++
                }
                catch {
                    Write-Host "  [ERR] $($_.FullName) -- $($_.Exception.Message)" -ForegroundColor Red
                    $loosePurgeSkipped++
                }
            }
        }
}

# ============================================================
# 2b. Tree-level purge (ExtraPurgeRoots — top-level entries, dir mtime)
# ============================================================
# Each top-level child of an ExtraPurgeRoot is treated as a wholesale-archived
# unit. Dir LastWriteTime reflects when content was last touched in place. If
# >365 days untouched, the whole tree is purged. Files inside are NOT individually
# evaluated — they keep their original mtimes from before archival, which would
# otherwise trigger premature purges of fresh archives.

foreach ($root in $ExtraPurgeRoots) {
    if (-not (Test-Path $root)) {
        Step "$root does not exist; skipping." "Yellow"
        continue
    }
    Step "Scanning $root top-level entries older than $ArchiveAgeDays days (tree-level)..."

    Get-ChildItem -LiteralPath $root -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $cutoff } |
        ForEach-Object {
            if ($DryRun) {
                Write-Host "  [DRY] delete tree $($_.FullName)" -ForegroundColor Yellow
            }
            else {
                try {
                    Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
                    Write-Host "  [OK]  deleted tree $($_.FullName)" -ForegroundColor Green
                    $loosePurged++
                }
                catch {
                    Write-Host "  [ERR] $($_.FullName) -- $($_.Exception.Message)" -ForegroundColor Red
                    $loosePurgeSkipped++
                }
            }
        }
}

# ============================================================
# Summary
# ============================================================

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
if ($DryRun) {
    Write-Host "DRY-RUN COMPLETE" -ForegroundColor Yellow
    Write-Host "Run with -Execute to actually move/delete."
}
else {
    Write-Host "ROTATION COMPLETE" -ForegroundColor Green
    Write-Host "  Inbox moved   : $inboxMoved"
    Write-Host "  Inbox skipped : $inboxSkipped"
    Write-Host "  Loose purged  : $loosePurged"
    Write-Host "  Purge skipped : $loosePurgeSkipped"
}
Write-Host "==========================================" -ForegroundColor Cyan

if ($inboxSkipped -gt 0 -or $loosePurgeSkipped -gt 0) { exit 2 } else { exit 0 }
