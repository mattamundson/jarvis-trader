# The only sanctioned local deploy path for the JARVIS dashboard.
#
# WHY THIS EXISTS
#   dashboard/ is simultaneously the source tree AND pm2's production serving
#   directory: the pm2 app `jarvis-dashboard` runs `next start --port 3010` out
#   of this folder, serving dashboard/.next. That means a bare `pnpm run build`
#   here IS a production deploy -- with no typecheck, no tests, and no restart.
#
#   Two failure modes follow from that, both observed in practice:
#     1. Build succeeds, nobody restarts pm2. The running server keeps an
#        in-memory manifest from the previous build while disk has the new one.
#     2. A broken build is published because nothing gated it.
#
#   This script makes the deploy atomic-ish and gated: everything that can fail
#   is run BEFORE pm2 is touched, and the result is verified by fetching the
#   served page and checking every chunk it references actually resolves --
#   not by trusting an exit code or a 200 on the HTML alone.
#
# USAGE
#   pwsh -File dashboard/scripts/deploy-local.ps1
#   pwsh -File dashboard/scripts/deploy-local.ps1 -SkipTests   # emergency only

[CmdletBinding()]
param(
    [switch]$SkipTests,
    [int]$Port = 3010,
    [string]$Pm2App = 'jarvis-dashboard'
)

$ErrorActionPreference = 'Stop'

$dashboardDir = Split-Path -Parent $PSScriptRoot
$baseUrl      = "http://127.0.0.1:$Port"

function Fail([string]$msg) {
    Write-Host ""
    Write-Host "DEPLOY ABORTED: $msg" -ForegroundColor Red
    Write-Host "pm2 was NOT restarted. The previously deployed build is still serving." -ForegroundColor Yellow
    exit 1
}

function Step([string]$name) {
    Write-Host ""
    Write-Host "==> $name" -ForegroundColor Cyan
}

Push-Location $dashboardDir
try {
    # ---- Everything that can fail happens before pm2 is touched -------------

    Step "Install dependencies (frozen lockfile)"
    pnpm install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { Fail "pnpm install failed (exit $LASTEXITCODE)" }

    Step "Typecheck (tsc --noEmit)"
    pnpm run typecheck
    if ($LASTEXITCODE -ne 0) { Fail "typecheck failed (exit $LASTEXITCODE)" }

    if (-not $SkipTests) {
        Step "Unit tests (node:test)"
        pnpm run test:unit
        if ($LASTEXITCODE -ne 0) { Fail "unit tests failed (exit $LASTEXITCODE)" }
    } else {
        Write-Host "WARNING: -SkipTests set; unit tests were NOT run." -ForegroundColor Yellow
    }

    $buildIdPath = Join-Path $dashboardDir '.next\BUILD_ID'
    $previousBuildId = if (Test-Path $buildIdPath) { (Get-Content $buildIdPath -Raw).Trim() } else { '<none>' }

    Step "Production build (previous BUILD_ID: $previousBuildId)"
    pnpm run build
    if ($LASTEXITCODE -ne 0) { Fail "next build failed (exit $LASTEXITCODE)" }

    if (-not (Test-Path $buildIdPath)) { Fail "build reported success but .next/BUILD_ID is missing" }
    $newBuildId = (Get-Content $buildIdPath -Raw).Trim()
    Write-Host "New BUILD_ID: $newBuildId" -ForegroundColor Green

    # ---- Only now do we touch the running service --------------------------

    Step "Restarting pm2 app '$Pm2App'"
    $restartsBefore = $null
    $desc = pm2 describe $Pm2App 2>$null
    if ($desc) {
        $m = ($desc | Select-String -Pattern 'restarts\s+.\s+(\d+)').Matches
        if ($m.Count -gt 0) { $restartsBefore = [int]$m[0].Groups[1].Value }
    }

    pm2 restart $Pm2App
    if ($LASTEXITCODE -ne 0) { Fail "pm2 restart failed (exit $LASTEXITCODE) -- service may be down, check 'pm2 list'" }

    # ---- Verify by observation, not by exit code ---------------------------

    Step "Waiting for $baseUrl to serve"
    $html = $null
    for ($i = 1; $i -le 30; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri "$baseUrl/" -UseBasicParsing -TimeoutSec 10
            if ($resp.StatusCode -eq 200) { $html = $resp.Content; break }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (-not $html) { Fail "dashboard did not return HTTP 200 at $baseUrl within 60s after restart" }
    Write-Host "HTTP 200 ($($html.Length) bytes)" -ForegroundColor Green

    # This is the check that actually catches a rebuild-without-restart: the
    # served HTML references chunk filenames, and a stale server happily serves
    # HTML whose chunks no longer exist on disk. A 200 on the page proves
    # nothing on its own.
    Step "Verifying every referenced static asset resolves"
    $assets = [regex]::Matches($html, '/_next/static/[^"''\\\s>]+') |
        ForEach-Object { $_.Value } | Sort-Object -Unique
    if ($assets.Count -eq 0) { Fail "served HTML referenced no /_next/static assets -- unexpected, refusing to call this healthy" }

    $badAssets = @()
    foreach ($a in $assets) {
        try {
            $r = Invoke-WebRequest -Uri "$baseUrl$a" -UseBasicParsing -TimeoutSec 10 -Method Head
            if ($r.StatusCode -ne 200) { $badAssets += "$a -> HTTP $($r.StatusCode)" }
        } catch {
            $badAssets += "$a -> $($_.Exception.Message)"
        }
    }

    if ($badAssets.Count -gt 0) {
        Write-Host "Assets that failed to resolve:" -ForegroundColor Red
        $badAssets | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
        Fail "$($badAssets.Count) of $($assets.Count) referenced assets did not return 200 -- the served build and the on-disk build disagree"
    }
    Write-Host "All $($assets.Count) referenced assets returned 200" -ForegroundColor Green

    Step "Persisting pm2 process list"
    pm2 save
    if ($LASTEXITCODE -ne 0) { Write-Host "WARNING: pm2 save failed (exit $LASTEXITCODE); deploy itself is fine." -ForegroundColor Yellow }

    Write-Host ""
    Write-Host "DEPLOY OK" -ForegroundColor Green
    Write-Host "  BUILD_ID : $previousBuildId -> $newBuildId" -ForegroundColor Gray
    Write-Host "  URL      : $baseUrl" -ForegroundColor Gray
    Write-Host "  Assets   : $($assets.Count)/$($assets.Count) resolved" -ForegroundColor Gray
    if ($null -ne $restartsBefore) {
        Write-Host "  pm2 restarts before this deploy: $restartsBefore" -ForegroundColor Gray
    }
}
finally {
    Pop-Location
}
