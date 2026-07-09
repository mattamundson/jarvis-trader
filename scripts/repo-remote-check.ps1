# repo-remote-check.ps1 -- verify every git repo has a fetchable remote
#
# Walks the same scan-roots as scan-uncommitted.ps1.
# For each repo: ensure at least one remote, then `git ls-remote` to verify it's reachable.
# Alerts on: no remote, unreachable remote, or unresolvable host.

[CmdletBinding()]
param(
    [string[]]$ScanRoots = @(
        "C:\Users\mattm\ThinkorSwim",
        "C:\Users\mattm\OneDrive",
        "C:\Users\mattm\Code",
        "C:\Users\mattm\Projects",
        "C:\Users\mattm\github-portfolio",
        "C:\Users\mattm\career-ops",
        "C:\Users\mattm\master-jarvis\second-brain"
    ),
    [int]$MaxDepth = 5,
    [int]$TimeoutSec = 15,
    [string]$OutFile = ""
)

function Find-GitRepos {
    param($Root, $Depth)
    if ($Depth -lt 0 -or -not (Test-Path $Root)) { return @() }
    if (Test-Path (Join-Path $Root ".git")) { return @($Root) }
    $repos = @()
    Get-ChildItem -LiteralPath $Root -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notmatch "^(node_modules|\.venv|venv|__pycache__|\.cache|AppData)$" } |
        ForEach-Object { $repos += Find-GitRepos -Root $_.FullName -Depth ($Depth - 1) }
    return $repos
}

$results = New-Object System.Collections.ArrayList
$allRepos = @()
foreach ($r in $ScanRoots) { $allRepos += Find-GitRepos -Root $r -Depth $MaxDepth }
$allRepos = $allRepos | Sort-Object -Unique
Write-Host "Checking remotes for $($allRepos.Count) repos..." -ForegroundColor Cyan

foreach ($repo in $allRepos) {
    Push-Location $repo
    try {
        $remoteList = (git remote 2>$null) -split "`n" | Where-Object { $_ }
        if (-not $remoteList) {
            $r = [PSCustomObject]@{
                severity = "HIGH"; path = $repo; remote = "(none)"; reachable = $false; detail = "No remote configured"
            }
            [void]$results.Add($r)
            Write-Host "[HIGH] $repo :: no remote" -ForegroundColor Red
            continue
        }
        $remoteName = $remoteList | Select-Object -First 1
        $remoteUrl = (git remote get-url $remoteName 2>$null) -join ""
        # Test reachability with ls-remote, time-bounded. Check git's exit code
        # (0 = reachable, 2 = no refs / unreachable) rather than parsing stderr —
        # PowerShell wraps git's stderr lines as RemoteException/NativeCommandError,
        # whose trace contains "Error" and falsely matched any /error/ regex.
        $job = Start-Job -ScriptBlock {
            param($p)
            Set-Location $p
            $null = git ls-remote --exit-code 2>&1
            return $LASTEXITCODE
        } -ArgumentList $repo
        $finished = Wait-Job -Job $job -Timeout $TimeoutSec
        if (-not $finished) {
            Stop-Job -Job $job -ErrorAction SilentlyContinue
            Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
            $r = [PSCustomObject]@{
                severity = "MEDIUM"; path = $repo; remote = $remoteUrl; reachable = $false; detail = "ls-remote timed out (${TimeoutSec}s)"
            }
            [void]$results.Add($r)
            Write-Host "[MEDIUM] $repo :: timeout" -ForegroundColor Yellow
            continue
        }
        $exitCode = (Receive-Job -Job $job) | Select-Object -Last 1
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
        if ($job.State -eq "Completed" -and $exitCode -eq 0) {
            $r = [PSCustomObject]@{
                severity = "OK"; path = $repo; remote = $remoteUrl; reachable = $true; detail = ""
            }
            [void]$results.Add($r)
            Write-Host "[OK] $repo :: $remoteUrl" -ForegroundColor Green
        }
        else {
            $r = [PSCustomObject]@{
                severity = "MEDIUM"; path = $repo; remote = $remoteUrl; reachable = $false; detail = "git exit=$exitCode"
            }
            [void]$results.Add($r)
            Write-Host "[MEDIUM] $repo :: unreachable ($remoteUrl) exit=$exitCode" -ForegroundColor Yellow
        }
    }
    finally {
        Pop-Location
    }
}

$highs = ($results | Where-Object severity -EQ "HIGH").Count
Write-Host ""
Write-Host "=== SUMMARY ===" -ForegroundColor Cyan
Write-Host "  HIGH (no remote)    : $highs"
Write-Host "  MEDIUM (unreachable): $(($results | Where-Object severity -EQ 'MEDIUM').Count)"
Write-Host "  OK                  : $(($results | Where-Object severity -EQ 'OK').Count)"

if ($OutFile) {
    $results | ConvertTo-Json -Depth 5 | Set-Content -Path $OutFile -Encoding UTF8
}

if ($highs -gt 0) { exit 2 } else { exit 0 }
