# memory-hygiene.ps1 -- monthly MEMORY.md hygiene check
#
# Reads ~/.claude/projects/C--windows-system32/memory/MEMORY.md, verifies:
#   1. Total line count is under threshold (default 200)
#   2. Each markdown link to a .md file points to an existing file in same dir
#
# Writes JSON state to .memory-hygiene-state.json. Exits 2 on any issue.

[CmdletBinding()]
param(
    [string]$MemoryDir = "C:\Users\mattm\.claude\projects\C--windows-system32\memory",
    [int]$LineThreshold = 200,
    [string]$StateFile = "C:\Users\mattm\scripts\.memory-hygiene-state.json"
)

$ErrorActionPreference = "Continue"
$indexPath = Join-Path $MemoryDir "MEMORY.md"

$result = [ordered]@{
    timestamp     = (Get-Date -Format "o")
    indexLines    = 0
    overThreshold = $false
    brokenRefs    = @()
    issues        = @()
}

if (-not (Test-Path $indexPath)) {
    $result.issues += "MEMORY.md not found at $indexPath"
    Write-Host "[FAIL] MEMORY.md not found" -ForegroundColor Red
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $StateFile -Encoding UTF8
    exit 2
}

$lines = Get-Content -LiteralPath $indexPath
$result.indexLines = $lines.Count

if ($lines.Count -gt $LineThreshold) {
    $result.overThreshold = $true
    $result.issues += "MEMORY.md has $($lines.Count) lines (threshold: $LineThreshold) -- consolidate oldest entries"
    Write-Host "[WARN] MEMORY.md is $($lines.Count) lines, exceeds $LineThreshold" -ForegroundColor Yellow
}

# Verify each markdown ref [Title](file.md) points to an existing file in same dir
$refPattern = '\[([^\]]+)\]\(([^)]+\.md)\)'
foreach ($line in $lines) {
    if ($line -match $refPattern) {
        $refFile = $matches[2]
        # Skip absolute URLs
        if ($refFile -match '^https?://') { continue }
        $refPath = Join-Path $MemoryDir $refFile
        if (-not (Test-Path $refPath)) {
            $result.brokenRefs += @{ title = $matches[1]; file = $refFile }
            Write-Host "[WARN] Broken ref: $refFile (linked as '$($matches[1])')" -ForegroundColor Yellow
        }
    }
}

if ($result.brokenRefs.Count -gt 0) {
    $result.issues += "$($result.brokenRefs.Count) broken file references in MEMORY.md"
}

$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $StateFile -Encoding UTF8

Write-Host ""
Write-Host "=== MEMORY HYGIENE COMPLETE ===" -ForegroundColor Cyan
Write-Host "  Index lines: $($result.indexLines)"
Write-Host "  Broken refs: $($result.brokenRefs.Count)"
Write-Host "  Issues:      $($result.issues.Count)"
Write-Host "  State file:  $StateFile"

if ($result.issues.Count -gt 0) { exit 2 }
exit 0
