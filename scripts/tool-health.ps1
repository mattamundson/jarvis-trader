# tool-health.ps1 -- verify canonical toolchain is intact
#
# Checks (per ~/.claude/CLAUDE.md proposed canonical setup):
#   - Python 3.13.3 base interpreter at expected path, runs --version
#   - Engine venv exists, base interpreter resolves, --version succeeds
#   - Node.js LTS on PATH
#   - pnpm on PATH
#   - Python 3.14 NOT installed (pre-GA, should be uninstalled)
#   - Forbidden plaintext-cred files do NOT exist at home root
#   - WindowsApps Store-Python stubs not on PATH ahead of real Python

[CmdletBinding()]
param(
    [string]$OutFile = ""
)

$results = New-Object System.Collections.ArrayList
function Add-Result {
    param($Check, $Status, $Detail)
    $r = [PSCustomObject]@{
        check  = $Check
        status = $Status
        detail = $Detail
    }
    [void]$results.Add($r)
    $color = switch ($Status) { "OK" { "Green" } "WARN" { "Yellow" } default { "Red" } }
    Write-Host ("[{0,-4}] {1}: {2}" -f $Status, $Check, $Detail) -ForegroundColor $color
}

# 1. Canonical Python 3.13
$py313 = "C:\Users\mattm\Python313\python.exe"
if (Test-Path $py313) {
    $ver = & $py313 --version 2>&1
    if ($ver -match "3\.13\.") {
        Add-Result "Python 3.13 base" "OK" $ver
    }
    else {
        Add-Result "Python 3.13 base" "WARN" "Found $ver at expected path"
    }
}
else {
    Add-Result "Python 3.13 base" "FAIL" "Missing at $py313"
}

# 2. Engine venv
$venvPython = "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv\Scripts\python.exe"
$venvCfg = "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv\pyvenv.cfg"
if (-not (Test-Path $venvPython)) {
    Add-Result "Engine venv exists" "FAIL" "Missing $venvPython"
}
else {
    $ver = & $venvPython --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Add-Result "Engine venv runs" "OK" $ver
    }
    else {
        Add-Result "Engine venv runs" "FAIL" "$venvPython failed: $ver"
    }
    if (Test-Path $venvCfg) {
        $cfg = Get-Content $venvCfg -Raw
        if ($cfg -match "WindowsApps") {
            Add-Result "Engine venv base" "FAIL" "Base points at WindowsApps Store Python (broken)"
        }
        elseif ($cfg -match "Python313") {
            Add-Result "Engine venv base" "OK" "Base = Python313 (canonical)"
        }
        else {
            # @() forces array context so [0] indexes the first matching LINE, not
            # the first CHARACTER of a single matched string. Without @(), a single
            # match collapses to a string and [0] yields "h" (first char of "home...").
            $line = @($cfg -split "`r?`n" | Where-Object { $_ -match "^home" })[0]
            Add-Result "Engine venv base" "WARN" "Base = $line"
        }
    }
}

# 3. Node.js
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
    $ver = & node --version 2>&1
    Add-Result "Node.js" "OK" "$ver at $($node.Source)"
}
else {
    Add-Result "Node.js" "FAIL" "Not on PATH (install LTS from nodejs.org)"
}

# 4. pnpm
$pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
if ($pnpm) {
    $ver = & pnpm --version 2>&1
    Add-Result "pnpm" "OK" "$ver at $($pnpm.Source)"
}
else {
    Add-Result "pnpm" "FAIL" "Not on PATH (npm install -g pnpm after Node LTS)"
}

# 5. Python 3.14 should NOT be present (still RC)
if (Test-Path "C:\Users\mattm\Python314\python.exe") {
    Add-Result "Python 3.14 absent" "WARN" "Python 3.14 (RC) still installed; uninstall via Apps & Features"
}
else {
    Add-Result "Python 3.14 absent" "OK" "Not present"
}

# 6. Forbidden cred files (per secret-hygiene.md)
$forbidden = @(
    "C:\Users\mattm\.env",
    "C:\Users\mattm\jarvis.env",
    "C:\Users\mattm\.secrets\keys.env"
)
$found = $forbidden | Where-Object { Test-Path $_ }
if ($found.Count -gt 0) {
    Add-Result "No plaintext creds at home" "FAIL" ("Found: " + ($found -join ", "))
}
else {
    Add-Result "No plaintext creds at home" "OK" "None of the forbidden paths exist"
}

# 7. PATH ordering -- Store stubs should not precede real Python
# Walk $pathDirs by index; Select-String on piped strings always reports
# LineNumber=1 (each piped string is its own input "line"), so the previous
# version silently passed when both were on PATH regardless of order.
$pathDirs = $env:PATH -split ";"
$winappsIdx = -1
$py313Idx = -1
for ($i = 0; $i -lt $pathDirs.Count; $i++) {
    if ($winappsIdx -lt 0 -and $pathDirs[$i] -match "WindowsApps") { $winappsIdx = $i }
    if ($py313Idx -lt 0 -and $pathDirs[$i] -match "Python313") { $py313Idx = $i }
}
if ($winappsIdx -ge 0 -and ($py313Idx -lt 0 -or $winappsIdx -lt $py313Idx)) {
    Add-Result "PATH ordering" "WARN" "WindowsApps (Store stubs) precedes Python313 -- Store stubs will resolve first"
}
else {
    Add-Result "PATH ordering" "OK" "Real Python precedes Store stubs"
}

# Summary
Write-Host ""
Write-Host "=== TOOL HEALTH SUMMARY ===" -ForegroundColor Cyan
$failed = ($results | Where-Object status -EQ "FAIL").Count
$warned = ($results | Where-Object status -EQ "WARN").Count
$ok = ($results | Where-Object status -EQ "OK").Count
Write-Host ("  OK   : {0}" -f $ok) -ForegroundColor Green
Write-Host ("  WARN : {0}" -f $warned) -ForegroundColor Yellow
Write-Host ("  FAIL : {0}" -f $failed) -ForegroundColor Red

if ($OutFile) {
    $results | ConvertTo-Json -Depth 5 | Set-Content -Path $OutFile -Encoding UTF8
}

if ($failed -gt 0) { exit 2 } else { exit 0 }
