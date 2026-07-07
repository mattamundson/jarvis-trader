# discord-github-digest.ps1
# Generates a daily Discord intelligence digest JSON and commits it to git.
# Schedule via: Jarvis-DiscordGitDigest (see install-discord-digest-task.ps1)
#
# Safe: stages ONLY data/discord-digests/YYYY-MM-DD.json -- never git add -A.

# Don't treat native-command stderr (Python logging) as terminating; explicit
# $LASTEXITCODE checks below handle real failures. See ~/.claude/rules/windows-pitfalls.md
# ("2>&1 wraps stderr as a RemoteException object").
$ErrorActionPreference = 'Continue'

# ---------------------------------------------------------------------------
# 1. Paths
# ---------------------------------------------------------------------------
$repoRoot  = Join-Path $PSScriptRoot ".."
$python    = Join-Path $repoRoot "engine\.venv\Scripts\python.exe"
$logFile   = Join-Path $repoRoot "logs\discord-digest-$(Get-Date -Format 'yyyyMMdd').log"

if (-not (Test-Path $python)) {
    Write-Error "Python venv not found at: $python"
    exit 1
}

# ---------------------------------------------------------------------------
# 2. Resolve target date (yesterday by default)
# ---------------------------------------------------------------------------
$targetDate = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")
$outputDir  = Join-Path $repoRoot "data\discord-digests"
$outputFile = Join-Path $outputDir "$targetDate.json"

New-Item -ItemType Directory -Force -Path $outputDir  | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $logFile) | Out-Null

# ---------------------------------------------------------------------------
# 3. Generate digest via Python
# ---------------------------------------------------------------------------
Write-Host "Generating Discord digest for $targetDate..."
Push-Location $repoRoot
& $python -m engine.discord.digest_generator `
    --date  $targetDate `
    --db    "engine/data/jarvis_trader.db" `
    --output $outputFile `
    2>&1 | Tee-Object -FilePath $logFile -Append
$genExit = $LASTEXITCODE

if ($genExit -ne 0 -or -not (Test-Path $outputFile)) {
    Write-Error "Digest generation failed (exit $genExit). Check $logFile"
    Pop-Location
    exit 1
}

# ---------------------------------------------------------------------------
# 4. Commit only the new digest file (never git add -A)
# ---------------------------------------------------------------------------
$relPath = "data/discord-digests/$targetDate.json"
git add $relPath
if ($LASTEXITCODE -ne 0) {
    Write-Warning "git add failed for $relPath"
    Pop-Location
    exit 1
}

# Only commit if something was staged (idempotent on re-runs)
$staged = git diff --cached --name-only
if ($staged) {
    git commit -m "data(discord): $targetDate digest"
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "git commit failed -- check for pre-commit hook issues"
        Pop-Location
        exit 1
    }
    Write-Host "Committed: $relPath"
} else {
    Write-Host "No changes staged -- digest for $targetDate already committed."
}

Pop-Location
exit 0
