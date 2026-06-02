# phase0-cleanup.ps1 -- post-rotation deletion sequence
#
# Run AFTER all 14 services in PHASE0_ROTATION_PLAYBOOK.md have been rotated
# and verified retrievable from 1Password vault `Amo Personal`.
#
# DO NOT run before rotation completes. Deleting plaintext copies before
# revoking the keys at issuers hides local exposure without reducing blast
# radius -- the keys remain valid wherever they leaked to.
#
# This script implements the 9-step deletion sequence from the playbook:
#   1. .aider/oauth-keys.env   (after SERVICE 2 OpenAI rotated)
#   2. .secrets/keys.env       (after SERVICE 1 + 2)
#   3. career-ops/.env         (after SERVICE 2, 5, 13)
#   4. GMS personal_agent/jarvis.env  (after all GMS service rotations)
#   5. ~/.env                  (after all services complete)
#   6. ~/jarvis.env            (after all services complete)
#   7. OneNote staging tree    (~/second-brain/raw/onenote/Matt's Notebook (2)/Quick Notes/)
#   8. OneNote AI Agents page-title export
#   9. ~/tmp/gbrain-staging/   (490 cred findings)
#  10. ~/RAI/                  (after SERVICE 14 RelevanceAI revocation)
#
# Plus derived exposures inside ~/.claude/ and ~/Projects/personal_agent/.
#
# Usage:
#   .\phase0-cleanup.ps1                    # default DRY RUN
#   .\phase0-cleanup.ps1 -Execute           # actually delete
#   .\phase0-cleanup.ps1 -Execute -SkipVerify   # skip the 'verify rotation done' gate
#
# Default behavior: DRY RUN unless -Execute is passed.

[CmdletBinding(DefaultParameterSetName = "DryRun")]
param(
    [Parameter(ParameterSetName = "DryRun")]
    [switch]$DryRun,

    [Parameter(ParameterSetName = "Execute")]
    [switch]$Execute,

    [switch]$SkipVerify
)

if (-not $Execute) { $DryRun = $true }
$ErrorActionPreference = "Continue"

function Step($msg, [string]$color = "Cyan") {
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts] $msg" -ForegroundColor $color
}

function Remove-Path {
    param([string]$Path, [string]$Reason)
    if (-not (Test-Path -LiteralPath $Path)) {
        Step "  SKIP $Path -- already gone" "DarkGray"
        return $true
    }
    $size = 0
    try {
        if ((Get-Item -LiteralPath $Path -Force).PSIsContainer) {
            $size = (Get-ChildItem -LiteralPath $Path -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
        }
        else {
            $size = (Get-Item -LiteralPath $Path -Force).Length
        }
    }
    catch {}
    $sizeMB = [math]::Round($size / 1MB, 2)
    if ($DryRun) {
        Step "  DRY-RUN would delete: $Path ($sizeMB MB) -- $Reason" "Yellow"
        return $true
    }
    Step "  Deleting: $Path ($sizeMB MB) -- $Reason" "Yellow"
    Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Continue
    if (Test-Path -LiteralPath $Path) {
        Step "    FAILED -- still exists" "Red"
        return $false
    }
    Step "    OK -- deleted ($sizeMB MB reclaimed)" "Green"
    return $true
}

# ============================================================
# Pre-flight: verify rotation done (unless -SkipVerify)
# ============================================================
if (-not $SkipVerify) {
    Step "Pre-flight: running phase0-verify.ps1 to confirm rotation completed..."
    $verify = Join-Path $PSScriptRoot "phase0-verify.ps1"
    if (Test-Path $verify) {
        $vOut = & $verify 2>&1 | Out-String
        # Ignore the "Forbidden files deleted" check (those still exist BEFORE this script runs).
        # Look for the 1Password / vault checks instead.
        if ($vOut -match "Vault items complete.*OK" -and $vOut -match "1Password signed in.*OK") {
            Step "  Pre-flight OK -- vault items present, 1P signed in" "Green"
        }
        else {
            Step "  Pre-flight FAILED. Either:" "Red"
            Step "    - Rotation not complete (vault items missing), OR" "Red"
            Step "    - 1Password not signed in (run 'op signin' first)" "Red"
            Step "  Re-run with -SkipVerify if you've already verified manually." "Red"
            exit 2
        }
    }
    else {
        Step "  WARN: phase0-verify.ps1 not found at $verify -- skipping pre-flight" "Yellow"
    }
}
else {
    Step "Skipping pre-flight verification (-SkipVerify)"
}

Write-Host ""
Step "========== Starting deletion sequence ==========" "Cyan"
Step "Mode: $(if ($DryRun) {'DRY RUN'} else {'EXECUTE'})" $(if ($DryRun) { 'Yellow' } else { 'Green' })
Write-Host ""

$reclaimedBytes = 0
function Track-Delete($path, $reason) {
    $sizeBefore = 0
    if (Test-Path -LiteralPath $path) {
        try {
            if ((Get-Item -LiteralPath $path -Force).PSIsContainer) {
                $sizeBefore = (Get-ChildItem -LiteralPath $path -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
            }
            else {
                $sizeBefore = (Get-Item -LiteralPath $path -Force).Length
            }
        }
        catch {}
    }
    $ok = Remove-Path -Path $path -Reason $reason
    if ($ok -and -not $DryRun) { $script:reclaimedBytes += $sizeBefore }
    if ($DryRun) { $script:reclaimedBytes += $sizeBefore }
}

# ============================================================
# Step 1-6: forbidden cred files (canonical 6)
# ============================================================
Step "Step 1: ~/.aider/oauth-keys.env (after SERVICE 2)"
Track-Delete "C:\Users\mattm\.aider\oauth-keys.env" "OPENAI_API_KEY only"

Step "Step 2: ~/.secrets/keys.env (after SERVICE 1 + 2)"
Track-Delete "C:\Users\mattm\.secrets\keys.env" "ANTHROPIC + OPENAI"

Step "Step 3: ~/career-ops/.env (after SERVICE 2, 5, 13)"
Track-Delete "C:\Users\mattm\career-ops\.env" "FIRECRAWL + OPENAI sk-proj + GOOGLE_CLIENT_*"

Step "Step 4: GMS personal_agent/jarvis.env (after all GMS rotations)"
Track-Delete "C:\Users\mattm\OneDrive\Greenfield Metal Sales\AI Agent Team\personal_agent\jarvis.env" "GMS 6th cred file"

Step "Step 5: ~/.env (after all services)"
Track-Delete "C:\Users\mattm\.env" "Most env vars"

Step "Step 6: ~/jarvis.env (after all services)"
Track-Delete "C:\Users\mattm\jarvis.env" "Most env vars"

# ============================================================
# Step 7-10: exposure-path scrubbing
# ============================================================
Step "Step 7: OneNote Quick Notes staging tree (51 pages with .env content quoted)"
Track-Delete "C:\Users\mattm\second-brain\raw\onenote\Matt's Notebook (2)\Quick Notes" "OneNote bulk exposure"

Step "Step 8: OneNote AI Agents page-title export (any AIzaSy*.md across all c:\onx exports)"
# 2026-05-05: original hardcoded path "Matt's Notebook-20260504 20-08" was moved to
# `_consumed-by-combine\` by the OneNote merge workflow. Verified 0 AIzaSy*.md files
# remain anywhere under c:\onx\ — but kept as safety net for future regression.
$onnoteAiAgents = @()
if (Test-Path "C:\onx\Exports") {
    $onnoteAiAgents = Get-ChildItem -Path "C:\onx\Exports" -Recurse -Filter "AIzaSy*.md" -ErrorAction SilentlyContinue
}
if ($onnoteAiAgents.Count -eq 0) {
    Step "  No AIzaSy*.md files found in c:\onx\ — already clean" "DarkGray"
}
foreach ($f in $onnoteAiAgents) {
    Track-Delete $f.FullName "Google API key page title"
}

Step "Step 9: ~/tmp/gbrain-staging/ (490 cred findings)"
Track-Delete "C:\Users\mattm\tmp\gbrain-staging" "Agent transcript exposure"

Step "Step 10: ~/RAI/ (after SERVICE 14 RelevanceAI revocation)"
Track-Delete "C:\Users\mattm\RAI" "Stalled prototype with exposed key"

# ============================================================
# Step 11+: derived exposures inside ~/.claude/ and ~/Projects/personal_agent/
# ============================================================
Step "Step 11a: ~/.claude/paste-cache/a7321d4b25c13720.txt (Render+Google)"
Track-Delete "C:\Users\mattm\.claude\paste-cache\a7321d4b25c13720.txt" "ephemeral paste cache"

Step "Step 11b: ~/.claude/projects/.../tool-results/* with embedded keys (4 files)"
$toolResultLeaks = @(
    "C:\Users\mattm\.claude\projects\C--Users-mattm-career-ops\1ec09cac-821a-4d59-b72e-df7b2a0c15e2\tool-results\b468x0qs2.txt",
    "C:\Users\mattm\.claude\projects\C--windows-system32\2987465d-3169-4854-8114-6319388e50a2\tool-results\bumn40ne3.txt",
    "C:\Users\mattm\.claude\projects\C--windows-system32\7ae38aa0-38c5-46ed-98ff-2afe9d23fabc\tool-results\b6hkm9c2n.txt",
    "C:\Users\mattm\.claude\projects\C--windows-system32\d2fa3bd6-a625-40b6-8a2c-4f4e90eaa53d\tool-results\bpyjzq00x.txt"
)
foreach ($f in $toolResultLeaks) { Track-Delete $f "tool-results transcript with key" }

Step "Step 11c: ~/.claude/plans/before-i-close-this-swirling-axolotl.md (REDACT, not delete)"
Step "  REDACT MANUALLY: Render rnd_*, Google AIzaSy* values → <REDACTED-2026-05-04>" "Yellow"

Step "Step 11d: MEMORY.md gbrain-staging entry (REDACT)"
Step "  REDACT MANUALLY: ~/.claude/projects/C--windows-system32/memory/MEMORY.md and project_gbrain_staging_exposure_2026_05_04.md" "Yellow"

Step "Step 11e: ~/Code/jarvis-agent-gms/JARVIS_STATUS_COMPLETE.md (REDACT)"
Step "  REDACT MANUALLY: Anthropic key value" "Yellow"

Step "Step 11f: ~/.thinkorswim/login-browser-data-v28-1/Default/Local Storage/leveldb (CLEAR ToS browser cache)"
Step "  Manual step: close ThinkorSwim, then delete the leveldb dir" "Yellow"

# ============================================================
# Step 12: ~/Projects/personal_agent/ (after extraction confirmed at ~/Code/personal-agent-skills/)
# ============================================================
Step "Step 12: ~/Projects/personal_agent/ (after rotation -- reusable skills already extracted)"
$ppaSkills = "C:\Users\mattm\Code\personal-agent-skills"
if (-not (Test-Path $ppaSkills)) {
    Step "  ABORT: ~/Code/personal-agent-skills/ missing -- extracted skills not found, refusing to delete source" "Red"
}
else {
    Track-Delete "C:\Users\mattm\Projects\personal_agent" "GMS-flavored Jarvis tree (skills extracted to ~/Code/personal-agent-skills/)"
}

# ============================================================
# Summary
# ============================================================
$reclaimedMB = [math]::Round($reclaimedBytes / 1MB, 1)
$reclaimedGB = [math]::Round($reclaimedBytes / 1GB, 2)
Write-Host ""
Step "========== SUMMARY ==========" "Cyan"
Step "Mode: $(if ($DryRun) {'DRY RUN'} else {'EXECUTED'})"
Step "Total $(if ($DryRun) {'would-reclaim'} else {'reclaimed'}): $reclaimedMB MB ($reclaimedGB GB)"

if ($DryRun) {
    Write-Host ""
    Step "DRY RUN -- nothing deleted. Re-run with -Execute to perform deletions." "Yellow"
}
else {
    Write-Host ""
    Step "Running phase0-verify.ps1 for sign-off..." "Cyan"
    $verify = Join-Path $PSScriptRoot "phase0-verify.ps1"
    if (Test-Path $verify) { & $verify }
}
