# scan-credentials.ps1 -- surface plaintext credential leaks under ~/
#
# Implements the rules in ~/.claude/rules/secret-hygiene.md.
# Default mode is read-only: prints findings to stdout + writes an alert log.
# Exits non-zero if any HIGH-severity finding (used by scheduled agents).
#
# Usage:
#   .\scan-credentials.ps1                  # full scan, console output
#   .\scan-credentials.ps1 -Quiet           # only output high-severity hits
#   .\scan-credentials.ps1 -OutFile path    # also write JSON results

[CmdletBinding()]
param(
    [switch]$Quiet,
    [string]$OutFile = "",
    [string]$ScanRoot = "C:\Users\mattm"
)

$ErrorActionPreference = "Continue"

# Patterns that indicate plaintext secrets. Each triggers a HIGH finding.
$HighPatterns = @{
    "Anthropic API key" = "sk-ant-[a-zA-Z0-9_-]{20,}"
    # Negative-lookahead (?!ant-) prevents Anthropic keys from also matching this pattern.
    "OpenAI API key"    = "sk-(?:proj-|admin-)?(?!ant-)[a-zA-Z0-9_-]{30,}"
    "Google API key"    = "AIzaSy[a-zA-Z0-9_-]{30,}"
    "AWS access key"    = "AKIA[0-9A-Z]{16}"
    "GitHub PAT"        = "(?:ghp_|github_pat_)[a-zA-Z0-9_]{30,}"
    "Slack bot token"   = "xox[baprs]-[a-zA-Z0-9-]{10,}"
    "Render API key"    = "rnd_[a-zA-Z0-9]{20,}"
    "Private RSA key"   = "-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
}

# Forbidden paths that should NOT exist (per secret-hygiene.md).
# Updated 2026-05-03 round 3: peer session enumerated 4th forbidden file.
$ForbiddenPaths = @(
    "$ScanRoot\.env",
    "$ScanRoot\jarvis.env",
    "$ScanRoot\.secrets\keys.env",
    "$ScanRoot\.aider\oauth-keys.env"
)

# Where to look. Skip these dirs to avoid noise from binaries/caches.
$SkipDirs = @(
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "AppData", "OneDrive", ".cache", "Python313", "Python314",
    "WindowsImageBackup", "SWSetup", ".bun", ".local",
    "dashboard", ".pnpm-store"
)

# User-editable whitelist file: ~/scripts/scan-whitelist.txt
# One pattern per line, # for comments. Loaded into $SkipDirs.
$WhitelistFile = Join-Path $PSScriptRoot "scan-whitelist.txt"
if (Test-Path $WhitelistFile) {
    Get-Content $WhitelistFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#")) {
            $SkipDirs += $line
        }
    }
}

# Trusted files: legitimate secret stores managed by sanctioned tools.
# These will match credential patterns but are not leaks. Full paths only.
$TrustedFiles = @(
    "$ScanRoot\.claude\.credentials.json"   # Claude Code's own OAuth token store
)

# File extensions worth scanning.
$ScanExts = @(".env", ".envrc", ".txt", ".json", ".yaml", ".yml", ".ini",
              ".cfg", ".conf", ".toml", ".sh", ".ps1", ".py", ".js", ".ts",
              ".md", ".log")

$findings = New-Object System.Collections.ArrayList
$highCount = 0

function Add-Finding {
    param($Severity, $Type, $Path, $Detail)
    $f = [PSCustomObject]@{
        severity = $Severity
        type     = $Type
        path     = $Path
        detail   = $Detail
        ts       = (Get-Date -Format "o")
    }
    [void]$findings.Add($f)
    if ($Severity -eq "HIGH") { $script:highCount++ }
    if (-not $Quiet -or $Severity -eq "HIGH") {
        $color = switch ($Severity) {
            "HIGH"   { "Red" }
            "MEDIUM" { "Yellow" }
            default  { "Gray" }
        }
        Write-Host "[$Severity] $Type :: $Path" -ForegroundColor $color
        if ($Detail) { Write-Host "        $Detail" -ForegroundColor DarkGray }
    }
}

# 1. Forbidden-path check
foreach ($p in $ForbiddenPaths) {
    if (Test-Path $p) {
        Add-Finding "HIGH" "ForbiddenPath" $p "File exists at forbidden location per secret-hygiene.md"
    }
}

# 2. Pattern scan
Write-Host "Scanning $ScanRoot (this may take a minute)..." -ForegroundColor Cyan
$skipPattern = (($SkipDirs | ForEach-Object { [regex]::Escape($_.TrimEnd('\','/')) }) -join "|")

Get-ChildItem -Path $ScanRoot -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object {
        $rel = $_.FullName.Substring($ScanRoot.Length)
        ($rel -notmatch "\\($skipPattern)\\") -and
        ($TrustedFiles -notcontains $_.FullName) -and
        ($_.Length -lt 5MB) -and
        ($ScanExts -contains $_.Extension.ToLower())
    } |
    ForEach-Object {
        try {
            $content = Get-Content -LiteralPath $_.FullName -Raw -ErrorAction SilentlyContinue
            if ($null -eq $content) { return }
            foreach ($name in $HighPatterns.Keys) {
                $pattern = $HighPatterns[$name]
                if ($content -match $pattern) {
                    Add-Finding "HIGH" "Pattern:$name" $_.FullName "Matched $name pattern"
                }
            }
            # Plaintext-password heuristic: lines like password=foo or password: foo
            if ($content -match '(?im)^\s*(?:password|passwd|pwd)\s*[:=]\s*\S{4,}') {
                Add-Finding "MEDIUM" "PlaintextPassword" $_.FullName "Matches password=... pattern"
            }
        } catch {}
    }

# 3. Summary
Write-Host ""
Write-Host "=== SCAN COMPLETE ===" -ForegroundColor Cyan
Write-Host "Total findings: $($findings.Count)"
Write-Host "  HIGH  : $highCount"
Write-Host "  MEDIUM: $(($findings | Where-Object severity -eq 'MEDIUM').Count)"

if ($OutFile) {
    $findings | ConvertTo-Json -Depth 5 | Set-Content -Path $OutFile -Encoding UTF8
    Write-Host "Results: $OutFile"
}

if ($highCount -gt 0) {
    Write-Host "ACTION REQUIRED: rotate all matched credentials, then move to 1Password." -ForegroundColor Red
    exit 2
}
exit 0
