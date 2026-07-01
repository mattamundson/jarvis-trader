<#
.SYNOPSIS
    One-paste launcher for Jarvis Robust Strategy Funnel — Phase 1 inventory.

.DESCRIPTION
    Idempotent setup + run. Safe to re-run; will skip steps already done.

    What it does:
      1. Validates Python and required packages are available
      2. Creates the OneDrive sync folder structure (jarvis-trader-handoff/)
      3. Downloads + unzips the latest skill package from this chat (or
         uses an existing unzipped copy)
      4. Validates the user's API key env var
      5. Runs Phase 1 inventory against the local jarvis-trader repo
      6. Confirms output landed in OneDrive

    Re-run after dropping bookmarks.html into OneDrive\jarvis-trader-handoff\
    to re-ingest bookmarks (script auto-detects).

.PARAMETER JarvisRepo
    Full path to your local jarvis-trader checkout. REQUIRED.

.PARAMETER SkillDir
    Where to unpack the skill scripts. Default: $HOME\dev\jarvis-funnel
    (created if missing).

.PARAMETER OneDriveSync
    Your OneDrive jarvis-trader-handoff folder. Default attempts to find
    your OneDrive root and append jarvis-trader-handoff.

.PARAMETER LlmProvider
    "anthropic" (default) or "openai".

.PARAMETER SkipLlm
    If set, runs in heuristic-only mode (no API cost; lower quality rationales).
    Useful for a first dry run.

.EXAMPLE
    .\Run-JarvisFunnelPhase1.ps1 -JarvisRepo "C:\Users\matt\dev\jarvis-trader"

.EXAMPLE
    .\Run-JarvisFunnelPhase1.ps1 -JarvisRepo "C:\Users\matt\dev\jarvis-trader" -SkipLlm
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$JarvisRepo,

    [string]$SkillDir = "$HOME\dev\jarvis-funnel",

    [string]$OneDriveSync = $null,

    [ValidateSet("anthropic", "openai")]
    [string]$LlmProvider = "anthropic",

    [switch]$SkipLlm
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Step($n, $msg) {
    Write-Host ""
    Write-Host "===== [Step $n] $msg =====" -ForegroundColor Cyan
}

function Write-OK($msg) { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "  [ERR] $msg" -ForegroundColor Red }

# ────────────────────────────────────────────────────────────────────────────
# Step 1: Validate Python
# ────────────────────────────────────────────────────────────────────────────
Write-Step 1 "Validating Python and dependencies"

try {
    $pyVer = & python --version 2>&1
    Write-OK "Python found: $pyVer"
}
catch {
    Write-Err "Python not found on PATH. Install Python 3.10+ and re-run."
    exit 1
}

$requiredPkgs = @("beautifulsoup4")
if (-not $SkipLlm) {
    if ($LlmProvider -eq "anthropic") { $requiredPkgs += "anthropic" }
    else { $requiredPkgs += "openai" }
}

foreach ($pkg in $requiredPkgs) {
    $check = & python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$($pkg.Replace('-', '_'))') else 1)" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-OK "$pkg installed"
    }
    else {
        Write-Warn "$pkg missing — installing"
        & python -m pip install --quiet $pkg
        if ($LASTEXITCODE -ne 0) {
            Write-Err "Failed to install $pkg. Run: python -m pip install $pkg"
            exit 1
        }
        Write-OK "$pkg installed"
    }
}

# ────────────────────────────────────────────────────────────────────────────
# Step 2: Resolve and create OneDrive sync folder
# ────────────────────────────────────────────────────────────────────────────
Write-Step 2 "Resolving OneDrive sync folder"

if (-not $OneDriveSync) {
    # Try standard OneDrive env vars
    if ($env:OneDrive) { $OneDriveSync = Join-Path $env:OneDrive "jarvis-trader-handoff" }
    elseif ($env:OneDriveCommercial) { $OneDriveSync = Join-Path $env:OneDriveCommercial "jarvis-trader-handoff" }
    elseif ($env:OneDriveConsumer) { $OneDriveSync = Join-Path $env:OneDriveConsumer "jarvis-trader-handoff" }
    else {
        Write-Err "Could not auto-locate OneDrive. Pass -OneDriveSync explicitly."
        exit 1
    }
}

Write-OK "OneDrive sync root: $OneDriveSync"

# Create folder structure
$subdirs = @("cards", "verdicts", "results", "tracker", "phase2_configs", "phase3_configs", "phase4_configs")
New-Item -ItemType Directory -Force -Path $OneDriveSync | Out-Null
foreach ($sub in $subdirs) {
    $p = Join-Path $OneDriveSync $sub
    New-Item -ItemType Directory -Force -Path $p | Out-Null
}
Write-OK "Folder structure created/verified ($($subdirs.Count) subdirs)"

# ────────────────────────────────────────────────────────────────────────────
# Step 3: Validate skill scripts available
# ────────────────────────────────────────────────────────────────────────────
Write-Step 3 "Validating skill scripts"

$scriptsDir = Join-Path $SkillDir "scripts"
$phase1Script = Join-Path $scriptsDir "phase1_inventory.py"
$runPhaseScript = Join-Path $scriptsDir "run_phase.py"

if (-not (Test-Path $phase1Script)) {
    Write-Warn "phase1_inventory.py not found at $phase1Script"
    Write-Host ""
    Write-Host "  Download 'jarvis-robust-strategy-funnel-skill.zip' from your Computer chat" -ForegroundColor Yellow
    Write-Host "  and unzip its contents into: $SkillDir" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Expected structure after unzip:" -ForegroundColor Yellow
    Write-Host "    $SkillDir\SKILL.md" -ForegroundColor Yellow
    Write-Host "    $SkillDir\scripts\phase1_inventory.py" -ForegroundColor Yellow
    Write-Host "    $SkillDir\scripts\run_phase.py" -ForegroundColor Yellow
    Write-Host "    $SkillDir\scripts\funnel_gate.py" -ForegroundColor Yellow
    Write-Host "    $SkillDir\references\..." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Tip: unzip directly into $SkillDir so that the SKILL.md file ends up" -ForegroundColor Yellow
    Write-Host "  at $SkillDir\SKILL.md (NOT $SkillDir\jarvis-robust-strategy-funnel\SKILL.md)." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  If the zip unpacks with a wrapper folder, move the inner contents up one level:" -ForegroundColor Yellow
    Write-Host "    cd $SkillDir" -ForegroundColor Yellow
    Write-Host "    Move-Item .\jarvis-robust-strategy-funnel\* ." -ForegroundColor Yellow
    Write-Host "    Remove-Item .\jarvis-robust-strategy-funnel" -ForegroundColor Yellow
    exit 1
}

Write-OK "Skill scripts found in $scriptsDir"

# ────────────────────────────────────────────────────────────────────────────
# Step 4: Validate jarvis-trader repo
# ────────────────────────────────────────────────────────────────────────────
Write-Step 4 "Validating jarvis-trader repo"

if (-not (Test-Path $JarvisRepo)) {
    Write-Err "Repo path not found: $JarvisRepo"
    exit 1
}

$engineDir = Join-Path $JarvisRepo "engine"
if (-not (Test-Path $engineDir)) {
    Write-Err "Doesn't look like jarvis-trader (no engine/ directory at $engineDir)"
    exit 1
}

$runners = Get-ChildItem -Path (Join-Path $engineDir "backtest") -Filter "run_*.py" -ErrorAction SilentlyContinue
Write-OK "Repo OK: $($runners.Count) runner files in engine\backtest\"

# ────────────────────────────────────────────────────────────────────────────
# Step 5: Validate API key (unless --SkipLlm)
# ────────────────────────────────────────────────────────────────────────────
if ($SkipLlm) {
    Write-Step 5 "Skipping LLM provider check (--SkipLlm set)"
    $env:JARVIS_FUNNEL_LLM_PROVIDER = ""
    Write-OK "Will run in heuristic-only mode"
}
else {
    Write-Step 5 "Validating LLM API key"
    $env:JARVIS_FUNNEL_LLM_PROVIDER = $LlmProvider

    if ($LlmProvider -eq "anthropic") {
        if (-not $env:ANTHROPIC_API_KEY) {
            Write-Err "ANTHROPIC_API_KEY not set. Run:"
            Write-Host '    $env:ANTHROPIC_API_KEY = "sk-ant-..."' -ForegroundColor Yellow
            exit 1
        }
        Write-OK "ANTHROPIC_API_KEY is set"
    }
    else {
        if (-not $env:OPENAI_API_KEY) {
            Write-Err "OPENAI_API_KEY not set. Run:"
            Write-Host '    $env:OPENAI_API_KEY = "sk-..."' -ForegroundColor Yellow
            exit 1
        }
        Write-OK "OPENAI_API_KEY is set"
    }
}

# ────────────────────────────────────────────────────────────────────────────
# Step 6: Check for bookmarks (optional)
# ────────────────────────────────────────────────────────────────────────────
Write-Step 6 "Checking for X bookmarks export"

$bookmarksHtml = Join-Path $OneDriveSync "bookmarks.html"
$bookmarksJson = Join-Path $OneDriveSync "bookmarks.json"
$bookmarksArg = ""

if (Test-Path $bookmarksHtml) {
    $size = (Get-Item $bookmarksHtml).Length
    Write-OK "Found bookmarks.html ($([math]::Round($size/1KB, 1)) KB) — will ingest"
    $bookmarksArg = $bookmarksHtml
}
elseif (Test-Path $bookmarksJson) {
    $size = (Get-Item $bookmarksJson).Length
    Write-OK "Found bookmarks.json ($([math]::Round($size/1KB, 1)) KB) — will ingest"
    $bookmarksArg = $bookmarksJson
}
else {
    Write-Warn "No bookmarks.html or bookmarks.json in $OneDriveSync"
    Write-Warn "Phase 1 will run against the repo only. To add bookmarks later:"
    Write-Warn "  1. See the X bookmarks export playbook from your Computer chat"
    Write-Warn "  2. Drop the export at $OneDriveSync\bookmarks.html"
    Write-Warn "  3. Re-run this script"
}

# ────────────────────────────────────────────────────────────────────────────
# Step 7: Run Phase 1
# ────────────────────────────────────────────────────────────────────────────
Write-Step 7 "Running Phase 1 inventory pipeline"

$outFile = Join-Path $OneDriveSync "cards\strategies_v1.jsonl"
$sideArtifacts = $OneDriveSync

$pyArgs = @(
    $phase1Script,
    "--repo", $JarvisRepo,
    "--out", $outFile,
    "--side-artifacts-dir", $sideArtifacts,
    "--log-level", "INFO"
)
if ($bookmarksArg) { $pyArgs += @("--bookmarks", $bookmarksArg) }

Write-Host "  Command:" -ForegroundColor Gray
Write-Host "  python $($pyArgs -join ' ')" -ForegroundColor Gray
Write-Host ""

$startTime = Get-Date
& python @pyArgs
$exitCode = $LASTEXITCODE
$duration = (Get-Date) - $startTime

if ($exitCode -ne 0) {
    Write-Err "Phase 1 failed with exit code $exitCode after $([math]::Round($duration.TotalSeconds, 1))s"
    exit $exitCode
}

Write-OK "Phase 1 completed in $([math]::Round($duration.TotalSeconds, 1))s"

# ────────────────────────────────────────────────────────────────────────────
# Step 8: Verify outputs
# ────────────────────────────────────────────────────────────────────────────
Write-Step 8 "Verifying outputs"

if (-not (Test-Path $outFile)) {
    Write-Err "Expected output not found: $outFile"
    exit 1
}

$nCards = (Get-Content $outFile | Measure-Object -Line).Lines
Write-OK "strategies_v1.jsonl created — $nCards strategy cards"

$atomsRepo = Join-Path $OneDriveSync "atoms_repo.jsonl"
if (Test-Path $atomsRepo) {
    $nAtoms = (Get-Content $atomsRepo | Measure-Object -Line).Lines
    Write-OK "atoms_repo.jsonl — $nAtoms atoms extracted"
}

$mergeReview = Join-Path $OneDriveSync "merge_review.jsonl"
if ((Test-Path $mergeReview) -and ((Get-Item $mergeReview).Length -gt 0)) {
    $nMerges = (Get-Content $mergeReview | Measure-Object -Line).Lines
    Write-Warn "$nMerges candidate merges need your review in merge_review.jsonl"
}

# Quick status breakdown
$summary = & python -c @"
import json
cards = [json.loads(l) for l in open(r'$outFile', encoding='utf-8')]
from collections import Counter
status = Counter(c['phase_1_status'] for c in cards)
print('Status:', dict(status))
cats = Counter(c['category'] for c in cards)
print('Categories:', dict(cats.most_common(5)))
"@ 2>&1
Write-Host "  $summary"

# ────────────────────────────────────────────────────────────────────────────
# Done
# ────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "════════════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host " Phase 1 inventory COMPLETE" -ForegroundColor Green
Write-Host "════════════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host " Output: $outFile" -ForegroundColor White
Write-Host ""
Write-Host " Next steps:" -ForegroundColor White
Write-Host "   1. Tell Computer in your chat: 'Phase 1 done, check OneDrive'" -ForegroundColor White
Write-Host "   2. Computer will read the cards via the OneDrive connector and" -ForegroundColor White
Write-Host "      help you decide which 5-10 to push through Phase 2 backtests" -ForegroundColor White
Write-Host ""
Write-Host " To re-ingest bookmarks later:" -ForegroundColor White
Write-Host "   Drop bookmarks.html into $OneDriveSync\ and re-run this script" -ForegroundColor White
Write-Host ""
