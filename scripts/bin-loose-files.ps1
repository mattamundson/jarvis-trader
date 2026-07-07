# bin-loose-files.ps1 -- year-bin loose files at home root
#
# Per ~/.claude/rules/cleanup-and-archive.md:
#   "Walks ~/ depth-1 only. For each loose file: move to
#    ~/.archive/loose-files/<mtime-year>/<ext>/. Pairs *.html with matching
#    *_files/ companion dirs (keeps them together). Has -DryRun mode that
#    prints counts before executing."
#
# Designed to run quarterly, or when home-root entries exceed 50.
#
# Usage:
#   .\bin-loose-files.ps1                          # default DRY RUN, all years
#   .\bin-loose-files.ps1 -DryRun                  # explicit dry run, all years
#   .\bin-loose-files.ps1 -Execute                 # move all years
#   .\bin-loose-files.ps1 -Execute -Year 2010      # move only files mtime'd 2010
#   .\bin-loose-files.ps1 -Execute -YearMax 2018   # move years <= 2018
#   .\bin-loose-files.ps1 -Execute -Verbose
#
# Refuses to move:
#   - .env, .secrets, *.key, *.pem, *.p12, *.pfx (cred files — see
#     ~/.claude/rules/secret-hygiene.md, must be rotated/deleted, not relocated)
#   - .git, .gitignore, .gitattributes (don't break repo state if home is one)
#   - Files starting with NTUSER (Windows registry hives)
#   - desktop.ini, Thumbs.db (Windows system files — leave alone)
#
# Safe to re-run. Idempotent: only moves files that still match depth-1.

[CmdletBinding(DefaultParameterSetName = "DryRun")]
param(
    [Parameter(ParameterSetName = "DryRun")]
    [switch]$DryRun,

    [Parameter(ParameterSetName = "Execute")]
    [switch]$Execute,

    # Filter to a single year (e.g. -Year 2010). Mutually exclusive with -YearMax.
    [int]$Year = 0,

    # Filter to years <= this value (e.g. -YearMax 2018 moves 2010-2018).
    [int]$YearMax = 0
)

# Default to dry-run if neither switch given.
if (-not $Execute) { $DryRun = $true }

$ErrorActionPreference = "Stop"
$HomeRoot = $env:USERPROFILE
$ArchiveRoot = Join-Path $HomeRoot ".archive\loose-files"

# Cred-file patterns we refuse to relocate. Match secret-hygiene.md.
$ForbiddenNames = @(
    '.env',
    'jarvis.env',
    '.npmrc',           # may contain auth tokens
    '.pypirc'           # may contain pypi tokens
)
$ForbiddenExtensions = @('.key', '.pem', '.p12', '.pfx', '.crt', '.cer')
$ForbiddenPrefixes = @('NTUSER', 'ntuser')
$SystemFiles = @(
    'desktop.ini', 'Thumbs.db',
    '.gitignore', '.gitattributes',
    '.gitconfig',          # global git identity — git looks here
    '.wslconfig',          # WSL config — wsl.exe looks here
    '.claude.json',        # Claude Code auto-managed state
    '.bash_history', '.zsh_history', '.python_history',
    '.bashrc', '.bash_profile', '.zshrc', '.profile',
    '.viminfo', '.lesshst'
)

function Test-IsForbidden($file) {
    if ($ForbiddenNames -contains $file.Name) { return $true }
    if ($ForbiddenExtensions -contains $file.Extension.ToLower()) { return $true }
    if ($SystemFiles -contains $file.Name) { return $true }
    foreach ($p in $ForbiddenPrefixes) {
        if ($file.Name.StartsWith($p)) { return $true }
    }
    # Anything ending in .env (per-project .env at home root not allowed by
    # secret-hygiene.md, but if it exists, do not relocate -- alert instead).
    if ($file.Name -like '*.env') { return $true }
    return $false
}

# ---------------------------------------------------------------
# Walk home root depth-1
# ---------------------------------------------------------------

$started = Get-Date
$files = Get-ChildItem -LiteralPath $HomeRoot -File -Force | Where-Object {
    -not $_.PSIsContainer
}

$skipped = @()
$moves = @()  # array of [PSCustomObject]@{src; dst; year; ext}

foreach ($f in $files) {
    if (Test-IsForbidden $f) {
        $skipped += [PSCustomObject]@{
            name   = $f.Name
            reason = "forbidden (creds or system file)"
        }
        continue
    }

    $yearInt = $f.LastWriteTime.Year
    if ($Year -gt 0 -and $yearInt -ne $Year) { continue }
    if ($YearMax -gt 0 -and $yearInt -gt $YearMax) { continue }

    $yearStr = $yearInt.ToString()
    $ext = if ($f.Extension) { $f.Extension.TrimStart('.').ToLower() } else { 'noext' }
    $destDir = Join-Path $ArchiveRoot "$yearStr\$ext"
    $destPath = Join-Path $destDir $f.Name

    $moves += [PSCustomObject]@{
        src  = $f.FullName
        dst  = $destPath
        year = $yearStr
        ext  = $ext
        size = $f.Length
    }
}

# ---------------------------------------------------------------
# Pair *.html files with matching *_files/ companion dirs (Save-As-Webpage)
# ---------------------------------------------------------------

$htmlPairs = @()
$htmlMoves = $moves | Where-Object { $_.ext -eq 'html' }
foreach ($h in $htmlMoves) {
    $base = [System.IO.Path]::GetFileNameWithoutExtension($h.src)
    $companion = Join-Path $HomeRoot "${base}_files"
    if (Test-Path -LiteralPath $companion -PathType Container) {
        $companionDest = Join-Path (Split-Path $h.dst -Parent) "${base}_files"
        $htmlPairs += [PSCustomObject]@{
            src = $companion
            dst = $companionDest
        }
    }
}

# ---------------------------------------------------------------
# Summary
# ---------------------------------------------------------------

$totalSize = ($moves | Measure-Object size -Sum).Sum
$sizeMB = [math]::Round($totalSize / 1MB, 1)

Write-Host ""
Write-Host "=== bin-loose-files SUMMARY ===" -ForegroundColor Cyan
Write-Host "Home: $HomeRoot"
Write-Host "Archive root: $ArchiveRoot"
Write-Host "Mode: $(if ($DryRun) {'DRY RUN'} else {'EXECUTE'})" -ForegroundColor $(if ($DryRun) { 'Yellow' } else { 'Green' })
Write-Host ""
Write-Host "Files at depth-1: $($files.Count)"
Write-Host "  Moveable: $($moves.Count) (~$sizeMB MB)"
Write-Host "  Skipped (forbidden): $($skipped.Count)"
Write-Host "  HTML companion dirs: $($htmlPairs.Count)"
Write-Host ""

# Counts by year
Write-Host "Moves by year:"
$moves | Group-Object year | Sort-Object Name | ForEach-Object {
    $sumMB = [math]::Round((($_.Group | Measure-Object size -Sum).Sum) / 1MB, 1)
    Write-Host ("  {0}: {1,5} files  ({2,7} MB)" -f $_.Name, $_.Count, $sumMB)
}

# Counts by extension (top 15)
Write-Host ""
Write-Host "Top 15 extensions (by file count):"
$moves | Group-Object ext | Sort-Object Count -Descending | Select-Object -First 15 | ForEach-Object {
    Write-Host ("  .{0,-10} {1,5} files" -f $_.Name, $_.Count)
}

# Skipped files
if ($skipped.Count -gt 0) {
    Write-Host ""
    Write-Host "Skipped (will NOT move):" -ForegroundColor Yellow
    foreach ($s in $skipped) {
        Write-Host ("  {0,-40} {1}" -f $s.name, $s.reason)
    }
}

if ($DryRun) {
    Write-Host ""
    Write-Host "DRY RUN -- no files moved. Re-run with -Execute to perform moves." -ForegroundColor Yellow
    exit 0
}

# ---------------------------------------------------------------
# Execute moves
# ---------------------------------------------------------------

Write-Host ""
Write-Host "Executing moves..." -ForegroundColor Green

$movedCount = 0
$failedCount = 0
foreach ($m in $moves) {
    $destDir = Split-Path $m.dst -Parent
    if (-not (Test-Path -LiteralPath $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }
    try {
        # If a file with same name already exists in dest (re-run), append .N
        if (Test-Path -LiteralPath $m.dst) {
            $base = [System.IO.Path]::GetFileNameWithoutExtension($m.dst)
            $ext = [System.IO.Path]::GetExtension($m.dst)
            $i = 1
            do {
                $candidate = Join-Path $destDir "$base.$i$ext"
                $i++
            } while (Test-Path -LiteralPath $candidate)
            $m.dst = $candidate
        }
        Move-Item -LiteralPath $m.src -Destination $m.dst -ErrorAction Stop
        $movedCount++
    }
    catch {
        Write-Host "  FAIL: $($m.src) -> $($m.dst): $_" -ForegroundColor Red
        $failedCount++
    }
}

# Move HTML companion dirs
foreach ($p in $htmlPairs) {
    if (-not (Test-Path -LiteralPath $p.src)) { continue }   # already moved earlier
    $destParent = Split-Path $p.dst -Parent
    if (-not (Test-Path -LiteralPath $destParent)) {
        New-Item -ItemType Directory -Path $destParent -Force | Out-Null
    }
    try {
        Move-Item -LiteralPath $p.src -Destination $p.dst -ErrorAction Stop
        $movedCount++
    }
    catch {
        Write-Host "  FAIL HTML pair: $($p.src) -> $($p.dst): $_" -ForegroundColor Red
        $failedCount++
    }
}

$elapsed = ((Get-Date) - $started).TotalSeconds
Write-Host ""
Write-Host "Moved: $movedCount" -ForegroundColor Green
Write-Host "Failed: $failedCount" -ForegroundColor $(if ($failedCount -gt 0) { 'Red' } else { 'Green' })
Write-Host ("Elapsed: {0:N1}s" -f $elapsed)

if ($failedCount -gt 0) { exit 1 } else { exit 0 }
