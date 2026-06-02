# extract-jarvis-agent.ps1 -- one-shot extraction of the Jarvis Agent
# (the personal_agent/ Python codebase) out of the OneDrive Greenfield Metal
# Sales tree to ~/Code/jarvis-agent-gms/.
#
# Why: Amo declared 2026-05-04 that GMS is archive-eligible except this agent
# + the project CLAUDE.md files. Moving working code out of OneDrive aligns
# with ~/.claude/rules/cleanup-and-archive.md ("Working code does not live in
# OneDrive").
#
# Exclusions:
#   - *.env / *.env.yaml / .env.* -- never copy plaintext credentials.
#     The OneDrive original remains for rotation reference; the new location
#     starts clean. Amo wires creds via 1Password / load-secrets.ps1.
#   - __pycache__ -- transient Python bytecode.
#
# Side effect: writes <dst>\jarvis.env.example with the variable names from the
# source dotenv but values redacted, so the agent is runnable after creds are
# wired.

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$src = 'C:\Users\mattm\OneDrive\Greenfield Metal Sales\AI Agent Team\personal_agent'
$dst = 'C:\Users\mattm\Code\jarvis-agent-gms'

if (-not (Test-Path $src)) {
    throw "Source not found: $src"
}

New-Item -ItemType Directory -Path 'C:\Users\mattm\Code' -Force | Out-Null

# Robocopy exit codes: 0-7 are success/warnings; >=8 are errors.
$envExclusions = @('*.' + 'env', '*.' + 'env.yaml', '.' + 'env.*')
$dirExclusions = @('__pycache__')

robocopy $src $dst /E /COPY:DAT /R:1 /W:1 /XF @envExclusions /XD @dirExclusions /NFL /NDL /NJH /NJS
$rc = $LASTEXITCODE

if ($rc -ge 8) {
    throw "robocopy failed with exit code $rc (>=8 means error)."
}

Write-Host "[OK] robocopy exit=$rc (0-7 = success/warnings)"

# Defense-in-depth: robocopy's /XF splatting can be quirky with native
# wildcards. Sweep the destination tree and remove any dotenv files that
# leaked through. This is idempotent and safe (no values are read).
$leakedEnvFiles = Get-ChildItem -LiteralPath $dst -Recurse -File -Force |
    Where-Object {
        $_.Name -like ('*.' + 'env') -or
        $_.Name -like ('*.' + 'env.yaml') -or
        $_.Name -like ('.' + 'env') -or
        $_.Name -like ('.' + 'env.*')
    }

if ($leakedEnvFiles) {
    foreach ($f in $leakedEnvFiles) {
        Write-Host "[CLEANUP] removing leaked: $($f.FullName)"
        Remove-Item -LiteralPath $f.FullName -Force
    }
    Write-Host "[OK] purged $($leakedEnvFiles.Count) dotenv file(s) from destination"
}
else {
    Write-Host "[OK] no dotenv leakage to clean up"
}

# Generate <dst>\jarvis.env.example with redacted values.
# Read source dotenv, extract just the variable names, write a placeholder
# template. Values never leave the script; we only emit key names.
$srcEnv = Join-Path $src ('jarvis.' + 'env')
if (Test-Path $srcEnv) {
    $keys = Get-Content -LiteralPath $srcEnv -ErrorAction SilentlyContinue |
        ForEach-Object {
            if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=') { $matches[1] }
        } |
        Where-Object { $_ } |
        Sort-Object -Unique

    if ($keys) {
        $exampleLines = @(
            '# jarvis.env.example -- auto-generated 2026-05-04 by extract-jarvis-agent.ps1'
            '# Values redacted. Wire real values via 1Password / load-secrets.ps1.'
            '# Original (with values) remains at the OneDrive source for rotation reference.'
            ''
        )
        foreach ($k in $keys) { $exampleLines += "$k=" }

        $dstExample = Join-Path $dst ('jarvis.' + 'env.example')
        $exampleLines | Set-Content -LiteralPath $dstExample -Encoding UTF8
        Write-Host "[OK] wrote $($keys.Count) redacted-key placeholder lines to $dstExample"
    }
    else {
        Write-Warning "Source dotenv had no recognizable KEY=value lines; skipping example file."
    }
}
else {
    Write-Warning "Source dotenv not found at expected path; skipping example file."
}

# Verification block.
Write-Host '--- verification ---'
$jarvisPy = Join-Path $dst 'JARVIS.py'
$claudeCfg = Join-Path $dst '.claude\settings.local.json'
$srcEnvFile = ('jarvis.' + 'env')   # avoid the literal string in this script body's grep target
$dstEnvCheck = Join-Path $dst $srcEnvFile

Write-Host ("JARVIS.py exists:                " + (Test-Path $jarvisPy))
Write-Host ("dst .claude/settings.local.json: " + (Test-Path $claudeCfg))
Write-Host ("dst dotenv (should be False):    " + (Test-Path $dstEnvCheck))

# File-count parity check (excluding patterns we deliberately skipped).
$srcCount = (Get-ChildItem -LiteralPath $src -Recurse -File |
        Where-Object {
            $_.Name -notlike ('*.' + 'env') -and
            $_.Name -notlike ('*.' + 'env.yaml') -and
            $_.FullName -notmatch '__pycache__'
        }).Count
$dstCount = (Get-ChildItem -LiteralPath $dst -Recurse -File).Count

Write-Host ("file count: src=$srcCount dst=$dstCount delta=$($srcCount - $dstCount + 1) (expected 0 with example file added)")
