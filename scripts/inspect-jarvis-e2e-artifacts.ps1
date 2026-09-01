param(
    [switch]$Execute,
    [switch]$ConfirmApprovedGeneratedArtifactCleanup
)

$ErrorActionPreference = "Stop"

$ExpectedRoot = Join-Path $env:USERPROFILE "Archive\2026\jarvis-temp-build-artifacts"
$Root = [System.IO.Path]::GetFullPath($ExpectedRoot)

function Assert-ExpectedRoot {
    param([string]$Path)

    $expected = [System.IO.Path]::GetFullPath((Join-Path $env:USERPROFILE "Archive\2026\jarvis-temp-build-artifacts"))
    if ($Path.TrimEnd("\") -ne $expected.TrimEnd("\")) {
        throw "Refusing unexpected artifact root: $Path"
    }
}

function Assert-ChildDirectory {
    param(
        [string]$Parent,
        [string]$Child
    )

    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd("\") + "\"
    $childFull = [System.IO.Path]::GetFullPath($Child).TrimEnd("\")
    if (-not $childFull.StartsWith($parentFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing path outside artifact root: $Child"
    }
    if ($childFull -eq $parentFull.TrimEnd("\")) {
        throw "Refusing to operate on artifact root itself: $Child"
    }
}

function Get-DirectorySizeBytes {
    param([string]$Path)

    $sum = (Get-ChildItem -LiteralPath $Path -Recurse -Force -File -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum).Sum
    if ($null -eq $sum) { return 0 }
    return [int64]$sum
}

Assert-ExpectedRoot -Path $Root

if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
    Write-Host "Artifact root not found: $Root"
    exit 0
}

$childDirs = @(Get-ChildItem -LiteralPath $Root -Directory -Force | Sort-Object LastWriteTime)
$records = foreach ($dir in $childDirs) {
    Assert-ChildDirectory -Parent $Root -Child $dir.FullName
    $bytes = Get-DirectorySizeBytes -Path $dir.FullName
    [pscustomobject]@{
        Name = $dir.Name
        FullName = $dir.FullName
        LastWriteTime = $dir.LastWriteTime
        Bytes = $bytes
        GB = [math]::Round($bytes / 1GB, 3)
    }
}

$totalBytes = [int64](($records | Measure-Object -Property Bytes -Sum).Sum ?? 0)
$drive = Get-PSDrive -Name C

Write-Host "Artifact root: $Root"
Write-Host "Mode: $(if ($Execute) { 'EXECUTE' } else { 'DRY RUN' })"
Write-Host "Child directories: $($records.Count)"
Write-Host "Artifact size: $([math]::Round($totalBytes / 1GB, 2)) GB"
Write-Host "C: free before: $([math]::Round($drive.Free / 1GB, 2)) GB"

if ($records.Count -gt 0) {
    Write-Host ""
    Write-Host "Largest child directories:"
    $records |
        Sort-Object Bytes -Descending |
        Select-Object -First 15 Name, GB, LastWriteTime |
        Format-Table -AutoSize
}

if (-not $Execute) {
    Write-Host ""
    Write-Host "Dry run only. To execute after explicit approval:"
    Write-Host ".\scripts\inspect-jarvis-e2e-artifacts.ps1 -Execute -ConfirmApprovedGeneratedArtifactCleanup"
    exit 0
}

if (-not $ConfirmApprovedGeneratedArtifactCleanup) {
    throw "Execution requires -ConfirmApprovedGeneratedArtifactCleanup after explicit approval."
}

foreach ($dir in $childDirs) {
    Assert-ChildDirectory -Parent $Root -Child $dir.FullName
    Remove-Item -LiteralPath $dir.FullName -Recurse -Force -ErrorAction Stop
}

$driveAfter = Get-PSDrive -Name C
Write-Host "Removed child directories: $($childDirs.Count)"
Write-Host "C: free after: $([math]::Round($driveAfter.Free / 1GB, 2)) GB"
