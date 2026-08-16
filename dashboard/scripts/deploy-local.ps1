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

function Get-EnvFileValue {
    param(
        [Parameter(Mandatory)] [string] $Path,
        [Parameter(Mandatory)] [string] $Name,
        [switch] $Required
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        if ($Required) { Fail "required env file not found: $Path" }
        return $null
    }

    $pattern = '^\s*' + [regex]::Escape($Name) + '\s*='
    $line = Select-String -LiteralPath $Path -Pattern $pattern | Select-Object -First 1
    if (-not $line) {
        if ($Required) { Fail "required variable $Name not found in $Path" }
        return $null
    }

    return (($line.Line -split '=', 2)[1]).Trim().Trim('"').Trim("'")
}

function Set-ProcessEnvFromFile {
    param(
        [Parameter(Mandatory)] [string] $Path,
        [Parameter(Mandatory)] [string] $Name,
        [switch] $Required
    )

    $value = Get-EnvFileValue -Path $Path -Name $Name -Required:$Required
    if ($value) {
        [Environment]::SetEnvironmentVariable($Name, $value, 'Process')
        return $true
    }
    return $false
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

    Step "Loading dashboard runtime env from .env.local"
    $dashboardEnv = Join-Path $dashboardDir '.env.local'
    $loadedRuntimeNames = @()
    if (Set-ProcessEnvFromFile -Path $dashboardEnv -Name 'ENGINE_API_KEY' -Required) {
        $loadedRuntimeNames += 'ENGINE_API_KEY'
    }
    foreach ($name in @(
        'NEXT_PUBLIC_ENGINE_API_KEY',
        'MASTER_API_KEY',
        'ENGINE_INTERNAL_URL',
        'NEXT_PUBLIC_MASTER_API_URL'
    )) {
        if (Set-ProcessEnvFromFile -Path $dashboardEnv -Name $name) {
            $loadedRuntimeNames += $name
        }
    }
    Write-Host ("Loaded runtime names for pm2 --update-env: {0} (values redacted)" -f ($loadedRuntimeNames -join ', ')) -ForegroundColor Green

    Step "Restarting pm2 app '$Pm2App'"
    pm2 restart $Pm2App --update-env
    if ($LASTEXITCODE -ne 0) { Fail "pm2 restart failed (exit $LASTEXITCODE) -- service may be down, check 'pm2 list'" }

    $pm2StatusSummary = 'not captured'
    Step "Capturing sanitized PM2 status for '$Pm2App'"
    $pm2SafeStatusScript = Join-Path $env:USERPROFILE 'scripts\pm2-safe-status.ps1'
    if (Test-Path -LiteralPath $pm2SafeStatusScript) {
        try {
            $pm2StatusRaw = & $pm2SafeStatusScript -Name $Pm2App -JlistTimeoutMs 8000
            $pm2StatusRows = @($pm2StatusRaw | ConvertFrom-Json)
            $pm2Status = $pm2StatusRows | Select-Object -First 1
            if ($pm2Status) {
                $pm2Source = if ($pm2Status.source) { $pm2Status.source } else { 'unknown' }
                $pm2Degraded = if ($null -ne $pm2Status.degraded) { [bool]$pm2Status.degraded } else { $false }
                $pm2StatusSummary = "status=$($pm2Status.status), pid=$($pm2Status.pid), restarts=$($pm2Status.restarts), source=$pm2Source, degraded=$pm2Degraded"
                Write-Host "PM2 status OK: $pm2StatusSummary" -ForegroundColor Green
            } else {
                $pm2StatusSummary = 'empty sanitized status response'
                Write-Host "WARNING: $pm2StatusSummary" -ForegroundColor Yellow
            }
        }
        catch {
            $pm2StatusSummary = "status capture failed: $($_.Exception.Message)"
            Write-Host "WARNING: $pm2StatusSummary" -ForegroundColor Yellow
        }
    } else {
        $pm2StatusSummary = "safe-status script not found at $pm2SafeStatusScript"
        Write-Host "WARNING: $pm2StatusSummary" -ForegroundColor Yellow
    }

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

    Step "Verifying broker endpoint stale-code contract"
    try {
        $broker = Invoke-RestMethod -Uri "$baseUrl/api/engine/brokers/positions" -UseBasicParsing -TimeoutSec 20
    }
    catch {
        Fail "dashboard proxy could not reach /api/engine/brokers/positions after restart: $($_.Exception.Message)"
    }

    if (-not $broker.schwab -or -not $broker.schwab.status) {
        Fail "broker endpoint response is missing schwab.status -- likely stale engine/dashboard contract"
    }
    if ($broker.schwab.status -eq 'disabled_by_policy') {
        $types = @($broker.reconciliation.discrepancies | ForEach-Object { $_.type } | Sort-Object -Unique)
        if ($types -contains 'paper_only') {
            Fail "stale broker reconciliation contract: Schwab is disabled_by_policy but equity discrepancies still include paper_only"
        }
        if (-not ($types -contains 'paper_unverified')) {
            Fail "stale broker reconciliation contract: Schwab is disabled_by_policy but paper_unverified discrepancies are absent"
        }
    }
    Write-Host ("Broker contract OK: schwab.status={0}, reconciliation.health={1}" -f $broker.schwab.status, $broker.reconciliation.health) -ForegroundColor Green

    Write-Host "Skipping pm2 save by design; PM2 dump files can persist process env values." -ForegroundColor Yellow

    Write-Host ""
    Write-Host "DEPLOY OK" -ForegroundColor Green
    Write-Host "  BUILD_ID : $previousBuildId -> $newBuildId" -ForegroundColor Gray
    Write-Host "  URL      : $baseUrl" -ForegroundColor Gray
    Write-Host "  Assets   : $($assets.Count)/$($assets.Count) resolved" -ForegroundColor Gray
    Write-Host "  Broker   : stale-code contract verified" -ForegroundColor Gray
    Write-Host "  PM2      : $pm2StatusSummary" -ForegroundColor Gray
}
finally {
    Pop-Location
}
