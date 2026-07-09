# scan-uncommitted.ps1 -- find git repos with uncommitted work or no remote
#
# For every git repo under the scan roots, report:
#   - branch
#   - last-commit date + age
#   - uncommitted change count
#   - untracked file count
#   - remote (or none)
# Flags HIGH severity when:
#   - uncommitted changes > 50 AND repo > 30 days stale
#   - OR no remote configured AND any uncommitted changes

[CmdletBinding()]
param(
    [string[]]$ScanRoots = @(
        "C:\Users\mattm\ThinkorSwim",
        "C:\Users\mattm\OneDrive",
        "C:\Users\mattm\Code",
        "C:\Users\mattm\Projects",
        "C:\Users\mattm\github-portfolio",
        "C:\Users\mattm\career-ops",
        "C:\Users\mattm\master-jarvis\second-brain",
        "C:\Users\mattm\.claude\skills"
    ),
    [string]$OutFile = "",
    [int]$MaxDepth = 5
)

$ErrorActionPreference = "Continue"
$results = New-Object System.Collections.ArrayList

function Find-GitRepos {
    param($Root, $Depth)
    if ($Depth -lt 0) { return }
    if (-not (Test-Path $Root)) { return }
    $gitDir = Join-Path $Root ".git"
    if (Test-Path $gitDir) {
        return @($Root)
    }
    $repos = @()
    Get-ChildItem -LiteralPath $Root -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notmatch "^(node_modules|\.venv|venv|__pycache__|\.cache|AppData)$" } |
        ForEach-Object {
            $repos += Find-GitRepos -Root $_.FullName -Depth ($Depth - 1)
        }
    return $repos
}

function Get-RepoState {
    param($RepoPath)
    Push-Location $RepoPath
    try {
        $branch       = (git branch --show-current 2>$null) -join ""
        $remoteList   = git remote 2>$null
        $remote       = if ($remoteList) { (git remote get-url ($remoteList | Select-Object -First 1) 2>$null) -join "" } else { "" }
        $lastCommit   = git log -1 --format="%cI" 2>$null
        $lastSubject  = git log -1 --format="%s" 2>$null
        $statusLines  = git status --porcelain 2>$null
        $modCount     = ($statusLines | Where-Object { $_ -match '^.[MD] ' -or $_ -match '^[MD]. ' }).Count
        $delCount     = ($statusLines | Where-Object { $_ -match '^.D ' -or $_ -match '^D. ' }).Count
        $untracked    = ($statusLines | Where-Object { $_ -match '^\?\?' }).Count

        $ageDays = $null
        if ($lastCommit) {
            try { $ageDays = [int]((Get-Date) - [datetime]$lastCommit).TotalDays } catch {}
        }

        $severity = "OK"
        if ([string]::IsNullOrEmpty($remote) -and ($modCount + $delCount + $untracked) -gt 0) {
            $severity = "HIGH"
        } elseif ($modCount + $delCount -gt 50 -and $ageDays -gt 30) {
            $severity = "HIGH"
        } elseif ($modCount + $delCount + $untracked -gt 20) {
            $severity = "MEDIUM"
        } elseif ($ageDays -gt 365) {
            $severity = "STALE"
        }

        return [PSCustomObject]@{
            severity        = $severity
            path            = $RepoPath
            branch          = $branch
            remote          = $remote
            last_commit_iso = $lastCommit
            last_subject    = $lastSubject
            age_days        = $ageDays
            modified        = $modCount
            deleted         = $delCount
            untracked       = $untracked
        }
    } finally {
        Pop-Location
    }
}

Write-Host "Scanning for git repos under $($ScanRoots.Count) roots..." -ForegroundColor Cyan
$allRepos = @()
foreach ($r in $ScanRoots) {
    $allRepos += Find-GitRepos -Root $r -Depth $MaxDepth
}
$allRepos = $allRepos | Sort-Object -Unique
Write-Host "Found $($allRepos.Count) repos.`n" -ForegroundColor Cyan

foreach ($repo in $allRepos) {
    $state = Get-RepoState $repo
    [void]$results.Add($state)
    $color = switch ($state.severity) {
        "HIGH"   { "Red" }
        "MEDIUM" { "Yellow" }
        "STALE"  { "DarkYellow" }
        default  { "Green" }
    }
    $remoteStr = if ($state.remote) { $state.remote } else { "(no remote)" }
    Write-Host ("[{0}] {1}" -f $state.severity, $state.path) -ForegroundColor $color
    Write-Host ("        branch={0} age={1}d mod={2} del={3} untracked={4}" -f `
        $state.branch, $state.age_days, $state.modified, $state.deleted, $state.untracked) -ForegroundColor DarkGray
    Write-Host ("        remote: {0}" -f $remoteStr) -ForegroundColor DarkGray
}

# Summary
$highs = $results | Where-Object severity -eq "HIGH"
Write-Host ""
Write-Host "=== SUMMARY ===" -ForegroundColor Cyan
Write-Host "Repos: $($results.Count)"
Write-Host "  HIGH  : $($highs.Count)"
Write-Host "  MEDIUM: $(($results | Where-Object severity -eq 'MEDIUM').Count)"
Write-Host "  STALE : $(($results | Where-Object severity -eq 'STALE').Count)"
Write-Host "  OK    : $(($results | Where-Object severity -eq 'OK').Count)"

if ($OutFile) {
    $results | ConvertTo-Json -Depth 5 | Set-Content -Path $OutFile -Encoding UTF8
    Write-Host "Results: $OutFile"
}

if ($highs.Count -gt 0) { exit 2 } else { exit 0 }
