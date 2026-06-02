# repair-engine-venv.ps1 -- rebuild the JARVIS engine venv from canonical Python 3.13
#
# Why: 2026-05-02 audit found the engine venv at
# C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv was created from a
# Store Python 3.12.10 that's no longer installed. pyvenv.cfg also shows the
# venv was originally at OneDrive\Documents\... and was moved to its current
# location -- patching paths won't work because installed packages compiled
# for 3.12.10. Full rebuild from Python313 is the only correct fix.
#
# Default mode is -DryRun: prints what would happen. Pass -Execute to act.
#
# Pre-flight: refuses to run if PM2 has jarvis-engine running. Stop it first
# with `pm2 stop jarvis-engine`.

[CmdletBinding()]
param(
    [switch]$Execute
)

$DryRun = -not $Execute

# Constants -- match restart_engine.ps1 style (full paths, no ambiguity).
$BaseInterpreter = "C:\Users\mattm\Python313\python.exe"
$EngineDir = "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine"
$VenvDir = Join-Path $EngineDir ".venv"
# requirements-core.txt is the CANONICAL bootstrap source per
# `engine/ecosystem.config.js:20` — it includes slowapi, claude-agent-sdk,
# torch, prometheus-fastapi-instrumentator, etc. that requirements.txt OMITS.
# The 2026-05-04 venv built from requirements.txt was missing 10 packages
# and could not boot the engine (slowapi import failure in middleware/rate_limit.py).
$RequirementsTxt = Join-Path $EngineDir "requirements-core.txt"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvCfg = Join-Path $VenvDir "pyvenv.cfg"

$started = Get-Date

function Step($msg, [string]$color = "Cyan") {
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts] $msg" -ForegroundColor $color
}

function Fail($msg) {
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

Step "repair-engine-venv.ps1 starting (mode: $(if ($DryRun) {'DRY-RUN'} else {'EXECUTE'}))"

# ============================================================
# Pre-flight checks
# ============================================================

Step "Pre-flight: verifying Python 3.13 base..."
if (-not (Test-Path $BaseInterpreter)) { Fail "Base Python missing at $BaseInterpreter" }
$baseVer = & $BaseInterpreter --version 2>&1
if ($baseVer -notmatch "3\.13\.") { Fail "Base interpreter is not 3.13.x: $baseVer" }
Step "  OK: $baseVer at $BaseInterpreter" "Green"

Step "Pre-flight: verifying engine + requirements-core.txt..."
if (-not (Test-Path $EngineDir)) { Fail "Engine dir missing at $EngineDir" }
if (-not (Test-Path $RequirementsTxt)) { Fail "requirements-core.txt missing at $RequirementsTxt" }
$reqLines = (Get-Content $RequirementsTxt | Measure-Object -Line).Lines
Step "  OK: requirements-core.txt has $reqLines lines" "Green"

Step "Pre-flight: checking PM2 jarvis-engine state..."
$pm2 = Get-Command pm2 -ErrorAction SilentlyContinue
if ($pm2) {
    $pm2list = & pm2 list 2>&1 | Out-String
    if ($pm2list -match "jarvis-engine\s*\|.*online") {
        Fail "jarvis-engine is currently RUNNING under PM2. Stop it first:`n  pm2 stop jarvis-engine`nThen rerun this script."
    }
    Step "  OK: jarvis-engine not running under PM2" "Green"
}
else {
    Step "  PM2 not on PATH; skipping (assuming engine not running)" "Yellow"
}

# ============================================================
# Backup current venv
# ============================================================

if (Test-Path $VenvDir) {
    $unixTs = [int][double]::Parse((Get-Date -UFormat %s))
    $backupName = "$VenvDir.broken-$unixTs"
    Step "Backing up current venv -> $backupName"
    if (-not $DryRun) {
        Rename-Item -Path $VenvDir -NewName (Split-Path $backupName -Leaf) -ErrorAction Stop
        if (-not $?) { Fail "Failed to rename current venv to $backupName" }
    }
    Step "  OK: current venv preserved (deletable later once new venv proven)" "Green"
}
else {
    Step "No existing venv to back up." "Yellow"
}

# ============================================================
# Build new venv
# ============================================================

Step "Creating new venv from $BaseInterpreter..."
if (-not $DryRun) {
    & $BaseInterpreter -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Fail "venv creation failed (exit $LASTEXITCODE)" }
    if (-not (Test-Path $VenvPython)) { Fail "venv created but python.exe missing at $VenvPython" }
}
Step "  OK: venv created at $VenvDir" "Green"

# ============================================================
# Bootstrap pip + install requirements
# ============================================================

Step "Upgrading pip..."
if (-not $DryRun) {
    & $VenvPython -m pip install --upgrade pip 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    if ($LASTEXITCODE -ne 0) { Fail "pip upgrade failed (exit $LASTEXITCODE)" }
}
Step "  OK: pip upgraded" "Green"

Step "Installing requirements ($reqLines lines)..."
Step "  This may take 5-15 minutes depending on network + wheel availability." "Yellow"
$pipFailed = $false
if (-not $DryRun) {
    & $VenvPython -m pip install -r $RequirementsTxt
    if ($LASTEXITCODE -ne 0) {
        $pipFailed = $true
        Step "pip install returned non-zero ($LASTEXITCODE). Some packages failed." "Red"
        Step "Common cause on this machine: native-build packages (numpy, ta-lib, scipy)" "Yellow"
        Step "  fail without a C compiler. Install one of:" "Yellow"
        Step "    winget install Microsoft.VisualStudio.2022.BuildTools" "DarkGray"
        Step "    or use only pre-built wheels: pip install --only-binary=:all: -r requirements-core.txt" "DarkGray"
        Step "" "Yellow"
        Step "If you want to roll back to the previous working venv:" "Yellow"
        Step "  Remove-Item -Recurse -Force '$VenvDir'" "DarkGray"
        Step "  Rename-Item '$backupName' '.venv'" "DarkGray"
    }
    else {
        Step "  OK: requirements installed" "Green"
    }
}

# ============================================================
# Patch pandas-ta Windows incompatibility (alligator.py posix.pread)
#
# pandas-ta 0.4.67b0 (the latest beta on PyPI as of 2026-05-04) ships
# `from posix import pread` at line 6 of overlap/alligator.py. The `posix`
# module is Linux-only and does not exist on Windows; the import raises
# ModuleNotFoundError at engine boot time. The line is dead code inside that
# file (pread is never called), so commenting it out is safe. This step is
# idempotent: if the line is already commented out (prior patch or a future
# release that fixes the bug) no change is written.
# Upstream issue: https://github.com/twopirllc/pandas-ta/issues (unfixed in 0.4.67b0)
# ============================================================

Step "Patching pandas-ta alligator.py (Windows posix.pread incompatibility)..."
$alligatorPath = Join-Path $VenvDir "Lib\site-packages\pandas_ta\overlap\alligator.py"
if (-not (Test-Path $alligatorPath)) {
    Step "  SKIP: alligator.py not found at $alligatorPath (pandas-ta not installed or path changed)" "Yellow"
}
else {
    $alligatorContent = Get-Content $alligatorPath -Raw
    $offendingPattern = "^from posix import pread"
    $alreadyPatched = $alligatorContent -match "(?m)^#from posix import pread"
    $needsPatch = $alligatorContent -match "(?m)^from posix import pread"

    if ($alreadyPatched -and -not $needsPatch) {
        Step "  OK: alligator.py already patched (posix.pread line already commented out)" "Green"
    }
    elseif ($needsPatch) {
        if (-not $DryRun) {
            $patched = $alligatorContent -replace "(?m)^from posix import pread", "#from posix import pread  # patched by repair-engine-venv.ps1 -- posix module is Linux-only"
            Set-Content -Path $alligatorPath -Value $patched -NoNewline -Encoding UTF8
            Step "  OK: alligator.py freshly patched -- 'from posix import pread' commented out" "Green"
        }
        else {
            Step "  DRY-RUN: would comment out 'from posix import pread' in $alligatorPath" "Yellow"
        }
    }
    else {
        Step "  INFO: offending line not found in alligator.py (may be fixed in installed version)" "Cyan"
    }
}

# ============================================================
# Verify
# ============================================================

Step "Verifying new venv..."
if (-not $DryRun) {
    $venvVer = & $VenvPython --version 2>&1
    if ($venvVer -notmatch "3\.13\.") {
        Fail "New venv reports unexpected version: $venvVer"
    }
    if (-not (Test-Path $VenvCfg)) { Fail "pyvenv.cfg missing" }
    $cfg = Get-Content $VenvCfg -Raw
    if ($cfg -match "WindowsApps") {
        Fail "pyvenv.cfg still references WindowsApps -- something went wrong"
    }
    if ($cfg -notmatch "Python313") {
        Step "WARN: pyvenv.cfg does not mention Python313 -- inspect manually" "Yellow"
        Write-Host $cfg -ForegroundColor DarkGray
    }
    else {
        Step "  OK: pyvenv.cfg points at Python313 (canonical)" "Green"
    }
    Step "  OK: $venvVer" "Green"

    # Critical-import smoke test. If pip install partial-failed, this catches the
    # silently-broken venv before we declare success.
    Step "Smoke-testing critical imports (fastapi, anthropic)..."
    $smokeOut = & $VenvPython -c "import fastapi, anthropic; print('SMOKE_OK')" 2>&1
    $smokeText = ($smokeOut | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $smokeText -notmatch "SMOKE_OK") {
        Step "FATAL: critical imports failed in new venv. Output:" "Red"
        Write-Host $smokeText -ForegroundColor DarkGray
        Step "" "Yellow"
        Step "The previous working venv is preserved at $backupName -- to restore:" "Yellow"
        Step "  Remove-Item -Recurse -Force '$VenvDir'" "DarkGray"
        Step "  Rename-Item '$backupName' '.venv'" "DarkGray"
        exit 2
    }
    Step "  OK: fastapi + anthropic import cleanly" "Green"
}

# ============================================================
# Summary
# ============================================================

$elapsed = (Get-Date) - $started
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
if ($DryRun) {
    Write-Host "DRY-RUN COMPLETE" -ForegroundColor Yellow
    Write-Host "Run again with -Execute to actually rebuild the venv." -ForegroundColor Yellow
}
elseif ($pipFailed) {
    Write-Host "REPAIR PARTIAL -- pip install had failures (see above)" -ForegroundColor Red
    Write-Host ("Elapsed: {0:N1} minutes" -f $elapsed.TotalMinutes)
    Write-Host ""
    Write-Host "The smoke test passed (fastapi + anthropic importable), but other"
    Write-Host "packages may be missing. Verify with:"
    Write-Host "  & '$VenvPython' -m pip list | Measure-Object -Line"
    Write-Host ""
    Write-Host "Backup at $backupName preserved if rollback needed."
    exit 1
}
else {
    Write-Host "REPAIR COMPLETE" -ForegroundColor Green
    Write-Host ("Elapsed: {0:N1} minutes" -f $elapsed.TotalMinutes)
    Write-Host ""
    Write-Host "Next steps:"
    Write-Host "  1. Run C:\Users\mattm\scripts\tool-health.ps1 -- expect 'Engine venv base: OK'"
    Write-Host "  2. cd $EngineDir; .\.venv\Scripts\python.exe -c 'import fastapi, anthropic; print(\"OK\")'"
    Write-Host "  3. cd C:\Users\mattm\ThinkorSwim\jarvis-trader; .\restart_engine.ps1"
    Write-Host ""
    Write-Host "If the engine boots cleanly, you can delete the backup:"
    Write-Host "  Remove-Item -Recurse -Force '$VenvDir.broken-*'"
}
Write-Host "==========================================" -ForegroundColor Cyan
