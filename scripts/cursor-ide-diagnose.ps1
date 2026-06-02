# cursor-ide-diagnose.ps1 -- diagnose the broken Cursor IDE CLI shim
#
# Background: 2026-05-03 Cursor Agent install showed the unrelated Cursor IDE
# at C:\Users\mattm\AppData\Local\Programs\cursor\ has a broken CLI shim --
# resources\app\out\cli.js is missing, so `cursor` from terminal errors with
# 'Cannot find module ... out/cli.js'. The GUI (Cursor.exe) launches fine
# from the Start menu; only the CLI is affected.
#
# This script reports what's there + what's missing, and prints repair
# instructions. Does NOT auto-reinstall (that's a download + run, your call).
#
# Usage:
#   .\cursor-ide-diagnose.ps1

[CmdletBinding()]
param()

$CursorRoot = "C:\Users\mattm\AppData\Local\Programs\cursor"
$AppRoot    = Join-Path $CursorRoot "resources\app"

function Check($label, $path, $required = $true) {
    if (Test-Path $path) {
        $sz = (Get-Item $path -ErrorAction SilentlyContinue).Length
        if ($sz) {
            Write-Host ("[OK]  {0,-30} {1} ({2:N0} bytes)" -f $label, $path, $sz) -ForegroundColor Green
        } else {
            Write-Host ("[OK]  {0,-30} {1}" -f $label, $path) -ForegroundColor Green
        }
        return $true
    } else {
        $color = if ($required) { "Red" } else { "DarkGray" }
        $tag   = if ($required) { "MISS" } else { "n/a" }
        Write-Host ("[{0,-4}] {1,-30} {2}" -f $tag, $label, $path) -ForegroundColor $color
        return $false
    }
}

Write-Host "=== Cursor IDE diagnostic ===" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $CursorRoot)) {
    Write-Host "Cursor IDE not installed at $CursorRoot." -ForegroundColor Yellow
    Write-Host "If you want the IDE, download from https://cursor.com/download"
    Write-Host "(For the CLI agent that you DID install, see cursor-agent at"
    Write-Host " $env:LOCALAPPDATA\cursor-agent\.)"
    exit 1
}

# Core install
$exe = Check "Cursor.exe (GUI)"     (Join-Path $CursorRoot "Cursor.exe")
$pkg = Check "package.json"          (Join-Path $AppRoot "package.json")
$bin = Check "bin/cursor (CLI shim)" (Join-Path $AppRoot "bin\cursor")
$out = Check "out/ (CLI bundle)"     (Join-Path $AppRoot "out") $true
$cli = Check "out/cli.js"            (Join-Path $AppRoot "out\cli.js") $true

# Start menu shortcut
$startLnk = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Cursor\Cursor.lnk"
$lnk = Check "Start menu shortcut"   $startLnk $false

# Version + product info
if ($pkg) {
    try {
        $pkgData = Get-Content (Join-Path $AppRoot "package.json") | ConvertFrom-Json
        Write-Host ""
        Write-Host "Installed version: $($pkgData.version) ($($pkgData.distro))" -ForegroundColor Cyan
        Write-Host "package.main:      $($pkgData.main)" -ForegroundColor Cyan
        if ($pkgData.main -match "out") {
            Write-Host "  --> package.json points at out/, but out/ exists: $out" -ForegroundColor Cyan
        }
    } catch {}
}

# CLI live-test
Write-Host ""
Write-Host "=== CLI live test ===" -ForegroundColor Cyan
try {
    $cliPath = Get-Command cursor -ErrorAction SilentlyContinue
    if ($cliPath) {
        Write-Host "cursor CLI on PATH: $($cliPath.Source)"
        $verOut = & cursor --version 2>&1 | Out-String
        if ($LASTEXITCODE -eq 0 -and $verOut -notmatch "Cannot find module") {
            Write-Host "[OK] cursor --version works" -ForegroundColor Green
            Write-Host $verOut -ForegroundColor DarkGray
        } else {
            Write-Host "[FAIL] cursor --version errors" -ForegroundColor Red
            Write-Host $verOut -ForegroundColor DarkGray
        }
    } else {
        Write-Host "cursor not on PATH" -ForegroundColor Yellow
    }
} catch {}

# Verdict + repair instructions
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "DIAGNOSIS" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

if ($exe -and -not $cli) {
    Write-Host @"
GUI works, CLI is broken.

The Cursor.exe binary is intact and the Start menu shortcut launches it
fine -- you can use the IDE normally via the Start menu.

The CLI shim at resources\app\bin\cursor expects out\cli.js (per package.json
"main": "./out/main.js"), but the out\ directory is missing entirely. This
is a partial-extraction state -- could have been an interrupted install,
antivirus quarantine, or manual delete.

REPAIR (recommended):
  1. Close any running Cursor.exe instances.
  2. Download the latest installer from https://cursor.com/download
  3. Run the installer -- it should reuse $CursorRoot and refresh the missing
     out\ directory.
  4. Verify: cursor --version  (in a NEW terminal)

REPAIR (alternative -- if a fresh install also fails):
  1. Uninstall via Settings > Apps > Cursor > Uninstall.
  2. Manually remove $CursorRoot if it persists.
  3. Reinstall from cursor.com/download.

This is unrelated to the cursor-agent CLI at $env:LOCALAPPDATA\cursor-agent\,
which works fine (verified 2026-05-03).
"@ -ForegroundColor Yellow
    exit 1
} elseif ($exe -and $cli) {
    Write-Host "Cursor IDE is healthy. Both GUI and CLI present and functional." -ForegroundColor Green
    exit 0
} else {
    Write-Host "Cursor IDE install is malformed -- core executable missing." -ForegroundColor Red
    Write-Host "Recommend: full uninstall + reinstall from cursor.com/download." -ForegroundColor Yellow
    exit 2
}
