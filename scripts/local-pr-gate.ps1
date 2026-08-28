<#
.SYNOPSIS
  Local pull-request gate for jarvis-trader when GitHub Actions cannot start.

.DESCRIPTION
  Runs the repo's local CI-equivalent checks against the current branch and
  writes a timestamped report to docs/ci-reports/. The default Standard profile
  is meant for PR triage: safety values, changed safety-file detection, a
  redacted security scan, engine lint/compile/mypy allowlist/fast pytest, and
  dashboard guards/typecheck/unit/component tests as applicable.

  Heavy checks are opt-in:
    -Full         runs dashboard build, dashboard E2E, and slow pytest too
    -IncludeBuild runs dashboard build only
    -IncludeComponent runs dashboard Vitest component tests
    -IncludeE2E   runs Playwright only after a build-capable profile
    -IncludeSlow  runs the slow pytest slice

  This script does not restart the engine, touch .env files, place orders, or
  merge PRs. It uses engine/.venv and dashboard/node_modules when present.

.EXAMPLE
  pwsh -NoProfile -File scripts\local-pr-gate.ps1

.EXAMPLE
  pwsh -NoProfile -File scripts\local-pr-gate.ps1 -Full -PrNumber 745
#>

[CmdletBinding()]
param(
    [string] $RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [string] $BaseRef = "origin/master",
    [ValidateSet("auto", "all", "engine", "dashboard", "safety", "security")]
    [string] $Scope = "auto",
    [int] $PrNumber = 0,
    [switch] $IncludeSlow,
    [switch] $IncludeBuild,
    [switch] $IncludeComponent,
    [switch] $IncludeE2E,
    [switch] $Full,
    [switch] $NoReport
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($Full) {
    $Scope = "all"
    $IncludeSlow = $true
    $IncludeBuild = $true
    $IncludeComponent = $true
    $IncludeE2E = $true
}

function Join-Quoted {
    param([Parameter(Mandatory)][string[]] $Items)
    return (($Items | ForEach-Object {
        if ($_ -match '\s') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join " ")
}

function Resolve-Tool {
    param(
        [Parameter(Mandatory)][string] $PreferredPath,
        [Parameter(Mandatory)][string] $FallbackName
    )
    if (Test-Path $PreferredPath) {
        return (Resolve-Path $PreferredPath).Path
    }
    $cmd = Get-Command $FallbackName -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    return $null
}

function Invoke-Step {
    param(
        [Parameter(Mandatory)][string] $Name,
        [Parameter(Mandatory)][string] $WorkingDirectory,
        [Parameter(Mandatory)][string] $FilePath,
        [Parameter(Mandatory)][string[]] $Arguments,
        [Parameter(Mandatory)][string] $LogPath
    )

    $started = Get-Date
    $commandLine = "$(Split-Path -Leaf $FilePath) $(Join-Quoted $Arguments)"
    Write-Host ""
    Write-Host "[local-pr-gate] START $Name"
    Write-Host "[local-pr-gate]   cwd: $WorkingDirectory"
    Write-Host "[local-pr-gate]   cmd: $commandLine"

    Push-Location $WorkingDirectory
    try {
        $output = & $FilePath @Arguments 2>&1
        $exitCode = if ($LASTEXITCODE -ne $null) { [int]$LASTEXITCODE } else { 0 }
    }
    catch {
        $output = @($_.Exception.Message)
        $exitCode = 1
    }
    finally {
        Pop-Location
    }

    $duration = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
    $header = @(
        "step: $Name",
        "cwd: $WorkingDirectory",
        "cmd: $commandLine",
        "exit: $exitCode",
        "duration_seconds: $duration",
        ""
    )
    Set-Content -Path $LogPath -Value ($header + $output) -Encoding UTF8

    $status = if ($exitCode -eq 0) { "PASS" } else { "FAIL" }
    Write-Host "[local-pr-gate] $status $Name ($duration sec)"

    return [pscustomobject]@{
        Name = $Name
        Status = $status
        ExitCode = $exitCode
        DurationSeconds = $duration
        LogPath = $LogPath
    }
}

function Get-GitLines {
    param([Parameter(Mandatory)][string[]] $Arguments)
    $lines = & git @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) {
        return @()
    }
    return @($lines)
}

function Get-PrBody {
    param([int] $Number)
    if ($Number -le 0) { return $null }
    $body = & gh pr view $Number --json body --jq ".body" 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    return ($body | Out-String)
}

function Test-AnyPrefix {
    param(
        [string[]] $Values,
        [string[]] $Prefixes
    )
    foreach ($value in $Values) {
        foreach ($prefix in $Prefixes) {
            if ($value -like "$prefix*") { return $true }
        }
    }
    return $false
}

function Get-LocalRelativePath {
    param(
        [Parameter(Mandatory)][string] $BasePath,
        [Parameter(Mandatory)][string] $TargetPath
    )

    $resolvedBase = (Resolve-Path $BasePath).Path
    $resolvedTarget = (Resolve-Path $TargetPath).Path
    if (-not $resolvedBase.EndsWith('\')) {
        $resolvedBase = $resolvedBase + '\'
    }
    $baseUri = New-Object System.Uri($resolvedBase)
    $targetUri = New-Object System.Uri($resolvedTarget)
    return ([System.Uri]::UnescapeDataString($baseUri.MakeRelativeUri($targetUri).ToString()) -replace '/', '\')
}

function Invoke-RedactedSecurityScan {
    param(
        [Parameter(Mandatory)][string] $RepoRoot,
        [Parameter(Mandatory)][string] $LogPath
    )

    $started = Get-Date
    Write-Host ""
    Write-Host "[local-pr-gate] START Security scan (redacted)"

    $tracked = @(Get-GitLines @("ls-files"))
    $secretNameHits = @($tracked | Where-Object {
        $_ -match '[Ss]ecret.*\.csv$|[Cc]redential.*\.csv$|\.pem$|\.p12$|\.pfx$'
    })

    $scanRoots = @("engine", "dashboard")
    $includeExt = @(".py", ".ts", ".tsx", ".js", ".csv", ".json", ".yaml", ".yml", ".md", ".txt")
    $excludedParts = @(".git", ".venv", "node_modules", ".next")
    $secretValuePattern = 'sk-ant-api[0-9]{2}-[A-Za-z0-9_-]{20,}|sk_live_[0-9a-zA-Z]{20,}|xox[baprs]-[0-9a-z-]{10,}|AKIA[0-9A-Z]{16}'
    $valueHits = New-Object System.Collections.Generic.List[string]

    foreach ($root in $scanRoots) {
        $rootPath = Join-Path $RepoRoot $root
        if (-not (Test-Path $rootPath)) { continue }
        Get-ChildItem -Path $rootPath -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
            $full = $_.FullName
            foreach ($part in $excludedParts) {
                if ($full -like "*\$part\*") { return }
            }
            if ($includeExt -notcontains $_.Extension) { return }
            $relative = $full.Substring($RepoRoot.Length).TrimStart('\') -replace "\\", "/"
            if ($tracked -notcontains $relative) { return }
            $text = Get-Content -Raw -LiteralPath $full -ErrorAction SilentlyContinue
            if ($text -match $secretValuePattern) {
                $valueHits.Add($relative) | Out-Null
            }
        }
    }

    $exitCode = 0
    if ($secretNameHits.Count -gt 0 -or $valueHits.Count -gt 0) {
        $exitCode = 1
    }

    $duration = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
    $log = New-Object System.Collections.Generic.List[string]
    $log.Add("step: Security scan (redacted)")
    $log.Add("exit: $exitCode")
    $log.Add("duration_seconds: $duration")
    $log.Add("")
    $log.Add("Secret-shaped filenames: $($secretNameHits.Count)")
    foreach ($hit in $secretNameHits) { $log.Add("  $hit") }
    $log.Add("Secret value files: $($valueHits.Count)")
    foreach ($hit in $valueHits) { $log.Add("  $hit") }
    $log.Add("")
    $log.Add("Raw secret values are intentionally not printed by this local scan.")
    Set-Content -Path $LogPath -Value $log -Encoding UTF8

    $status = if ($exitCode -eq 0) { "PASS" } else { "FAIL" }
    Write-Host "[local-pr-gate] $status Security scan (redacted) ($duration sec)"

    return [pscustomobject]@{
        Name = "Security scan (redacted)"
        Status = $status
        ExitCode = $exitCode
        DurationSeconds = $duration
        LogPath = $LogPath
    }
}

function Invoke-ToolchainPreflight {
    param(
        [Parameter(Mandatory)][string] $RepoRoot,
        [Parameter(Mandatory)][string] $Python,
        [string] $Pnpm,
        [Parameter(Mandatory)][string] $LogPath
    )

    $started = Get-Date
    Write-Host ""
    Write-Host "[local-pr-gate] START Toolchain preflight"

    $pythonProbe = (& $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}|{sys.prefix}')").Trim()
    $pythonParts = $pythonProbe -split '\|', 2
    $pythonVersion = $pythonParts[0]
    $pythonPrefix = if ($pythonParts.Count -gt 1) { $pythonParts[1] } else { "" }
    $pythonVersionOk = $pythonVersion -like "3.12.*"
    $localVenv = Join-Path $RepoRoot "engine\.venv"
    $pythonVenvOk = $pythonPrefix -like "$localVenv*"
    $pythonOk = $pythonVersionOk -and $pythonVenvOk
    $nodeVersion = $null
    $pnpmVersion = $null

    $node = Get-Command node -ErrorAction SilentlyContinue
    if ($node) {
        $nodeVersion = (& node --version 2>$null | Out-String).Trim()
    }
    if ($Pnpm) {
        $pnpmVersion = (& $Pnpm --version 2>$null | Out-String).Trim()
    }

    $exitCode = if ($pythonOk) { 0 } else { 1 }
    $duration = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("step: Toolchain preflight")
    $lines.Add("repo: $RepoRoot")
    $lines.Add("exit: $exitCode")
    $lines.Add("duration_seconds: $duration")
    $lines.Add("")
    $lines.Add("python: $Python")
    $lines.Add("python_version: $pythonVersion")
    $lines.Add("python_prefix: $pythonPrefix")
    $lines.Add("python_expected: repo engine/.venv on Python 3.12.x")
    $lines.Add("node_version: $nodeVersion")
    $lines.Add("pnpm: $Pnpm")
    $lines.Add("pnpm_version: $pnpmVersion")
    Set-Content -Path $LogPath -Value $lines -Encoding UTF8

    $status = if ($exitCode -eq 0) { "PASS" } else { "FAIL" }
    Write-Host "[local-pr-gate] $status Toolchain preflight ($duration sec)"
    if (-not $pythonOk) {
        Write-Host "[local-pr-gate]   expected repo engine/.venv on Python 3.12.x, got $pythonVersion at $pythonPrefix"
    }

    return [pscustomobject]@{
        Name = "Toolchain preflight"
        Status = $status
        ExitCode = $exitCode
        DurationSeconds = $duration
        LogPath = $LogPath
    }
}

$RepoRoot = (Resolve-Path $RepoRoot).Path
$engineRoot = Join-Path $RepoRoot "engine"
$dashboardRoot = Join-Path $RepoRoot "dashboard"
$reportRoot = Join-Path $RepoRoot "docs\ci-reports"
if (-not $NoReport -and -not (Test-Path $reportRoot)) {
    New-Item -ItemType Directory -Path $reportRoot -Force | Out-Null
}

Push-Location $RepoRoot
try {
    $branch = (& git branch --show-current).Trim()
    $head = (& git rev-parse HEAD).Trim()
    $base = (& git rev-parse $BaseRef).Trim()
    $headChanged = @(Get-GitLines @("diff", "--name-only", "$BaseRef...HEAD"))
    $unstagedChanged = @(Get-GitLines @("diff", "--name-only"))
    $stagedChanged = @(Get-GitLines @("diff", "--cached", "--name-only"))
    $untrackedChanged = @(Get-GitLines @("ls-files", "--others", "--exclude-standard"))
    $changed = @($headChanged + $unstagedChanged + $stagedChanged + $untrackedChanged |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Sort-Object -Unique)
    $statusLines = @(Get-GitLines @("status", "--short", "--branch"))

    if ($Scope -eq "auto") {
        $engineChanged = Test-AnyPrefix $changed @("engine/", "scripts/")
        $dashboardChanged = Test-AnyPrefix $changed @("dashboard/")
        if ($changed.Count -eq 0 -or ($engineChanged -and $dashboardChanged)) {
            $effectiveScope = "all"
        }
        elseif ($engineChanged) {
            $effectiveScope = "engine"
        }
        elseif ($dashboardChanged) {
            $effectiveScope = "dashboard"
        }
        else {
            $effectiveScope = "security"
        }
    }
    else {
        $effectiveScope = $Scope
    }

    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $runDir = Join-Path $reportRoot "local-pr-gate_$stamp"
    if (-not $NoReport) {
        New-Item -ItemType Directory -Path $runDir -Force | Out-Null
    }

    $results = New-Object System.Collections.Generic.List[object]
    $python = Resolve-Tool (Join-Path $engineRoot ".venv\Scripts\python.exe") "python"
    $ruff = Resolve-Tool (Join-Path $engineRoot ".venv\Scripts\ruff.exe") "ruff"
    $mypy = Resolve-Tool (Join-Path $engineRoot ".venv\Scripts\mypy.exe") "mypy"
    $pnpm = Resolve-Tool (Join-Path $env:APPDATA "npm\pnpm.cmd") "pnpm"

    if (-not $python) { throw "Python not found. Expected engine\.venv\Scripts\python.exe or python on PATH." }
    if (($effectiveScope -eq "all" -or $effectiveScope -eq "engine") -and -not $ruff) {
        throw "ruff not found. Expected engine\.venv\Scripts\ruff.exe or ruff on PATH."
    }
    if (($effectiveScope -eq "all" -or $effectiveScope -eq "engine") -and -not $mypy) {
        throw "mypy not found. Expected engine\.venv\Scripts\mypy.exe or mypy on PATH."
    }
    if (($effectiveScope -eq "all" -or $effectiveScope -eq "dashboard") -and -not $pnpm) {
        throw "pnpm not found. Expected npm pnpm.cmd shim or pnpm on PATH."
    }

    $log = {
        param([string] $Name)
        if ($NoReport) {
            return (Join-Path $env:TEMP ("local-pr-gate_" + ($Name -replace '[^A-Za-z0-9._-]', '_') + ".log"))
        }
        return (Join-Path $runDir (($Name -replace '[^A-Za-z0-9._-]', '_') + ".log"))
    }

    Write-Host "[local-pr-gate] repo: $RepoRoot"
    Write-Host "[local-pr-gate] branch: $branch"
    Write-Host "[local-pr-gate] head: $head"
    Write-Host "[local-pr-gate] base: $BaseRef ($base)"
    Write-Host "[local-pr-gate] scope: $effectiveScope"

    $runSafety = $effectiveScope -in @("all", "engine", "safety")
    $runSecurity = $effectiveScope -in @("all", "engine", "dashboard", "security")
    $runEngine = $effectiveScope -in @("all", "engine")
    $runDashboard = $effectiveScope -in @("all", "dashboard")

    if ($runEngine -or $runDashboard -or $runSafety) {
        $results.Add((Invoke-ToolchainPreflight $RepoRoot $python $pnpm (& $log "toolchain-preflight"))) | Out-Null
    }

    if ($runSafety) {
        $results.Add((Invoke-Step "Safety invariant values" $RepoRoot $python @("engine/scripts/check_safety_invariants.py") (& $log "safety-values"))) | Out-Null

        $safetyFiles = @($changed | Where-Object {
            $_ -match '^engine/config\.py$|^engine/risk/|^engine/notifications/openclaw_notifier\.py$|^engine/agents/trader\.py$'
        })
        $tagExit = 0
        $tagLines = New-Object System.Collections.Generic.List[string]
        $tagLines.Add("step: Safety changed-file tag check")
        $tagLines.Add("base: $BaseRef")
        $tagLines.Add("pr_number: $PrNumber")
        $tagLines.Add("")
        if ($safetyFiles.Count -eq 0) {
            $tagLines.Add("No safety-critical files changed.")
        }
        else {
            $tagLines.Add("Safety-critical files changed:")
            foreach ($file in $safetyFiles) { $tagLines.Add("  $file") }
            $body = Get-PrBody $PrNumber
            if ($body -and $body.Contains("[safety-review]")) {
                $tagLines.Add("")
                $tagLines.Add("PR body contains [safety-review].")
            }
            else {
                $tagLines.Add("")
                $tagLines.Add("Missing [safety-review] in PR body, or no -PrNumber was supplied.")
                $tagExit = 1
            }
        }
        $tagPath = & $log "safety-tag"
        Set-Content -Path $tagPath -Value $tagLines -Encoding UTF8
        $results.Add([pscustomobject]@{
            Name = "Safety changed-file tag check"
            Status = if ($tagExit -eq 0) { "PASS" } else { "FAIL" }
            ExitCode = $tagExit
            DurationSeconds = 0
            LogPath = $tagPath
        }) | Out-Null
    }

    if ($runSecurity) {
        $results.Add((Invoke-RedactedSecurityScan $RepoRoot (& $log "security-redacted"))) | Out-Null
    }

    if ($runEngine) {
        $results.Add((Invoke-Step "Engine ruff" $engineRoot $ruff @("check", ".", "--config", "ruff.toml") (& $log "engine-ruff"))) | Out-Null
        $results.Add((Invoke-Step "Engine compileall" $RepoRoot $python @("-m", "compileall", "-q", "engine", "-x", "(\.venv|node_modules|__pycache__|site-packages)") (& $log "engine-compileall"))) | Out-Null
        $results.Add((Invoke-Step "Engine mypy allowlist" $RepoRoot $mypy @(
            "engine/tests/test_paper_runner_engine_sync.py",
            "engine/tests/test_portfolio_paper_trade_post.py",
            "engine/routers/validation_router.py",
            "engine/execution/paper_trade_logger.py",
            "--ignore-missing-imports",
            "--config-file",
            "engine/pyproject.toml",
            "--explicit-package-bases",
            "--namespace-packages",
            "--follow-imports=skip"
        ) (& $log "engine-mypy-allowlist"))) | Out-Null
        $results.Add((Invoke-Step "Engine pytest fast" $engineRoot $python @(
            "-m", "pytest", "tests/", "-m", "not slow and not manual and not integration_ib", "-v", "--tb=short"
        ) (& $log "engine-pytest-fast"))) | Out-Null
        if ($IncludeSlow) {
            $results.Add((Invoke-Step "Engine pytest slow" $engineRoot $python @(
                "-m", "pytest", "tests/", "-m", "slow and not manual and not integration_ib", "-v", "--tb=short"
            ) (& $log "engine-pytest-slow"))) | Out-Null
        }
    }

    if ($runDashboard) {
        $results.Add((Invoke-Step "Dashboard guards" $dashboardRoot $pnpm @("run", "guards") (& $log "dashboard-guards"))) | Out-Null
        $results.Add((Invoke-Step "Dashboard typecheck" $dashboardRoot $pnpm @("run", "typecheck") (& $log "dashboard-typecheck"))) | Out-Null
        $results.Add((Invoke-Step "Dashboard unit tests" $dashboardRoot $pnpm @("run", "test:unit") (& $log "dashboard-unit"))) | Out-Null
        if ($IncludeComponent) {
            $results.Add((Invoke-Step "Dashboard component tests" $dashboardRoot $pnpm @("run", "test:component") (& $log "dashboard-component"))) | Out-Null
        }
        if ($IncludeBuild) {
            $buildLog = & $log "dashboard-build"
            $results.Add((Invoke-Step "Dashboard build" $dashboardRoot $pnpm @("run", "build") $buildLog)) | Out-Null
            $relativeBuildLog = Get-LocalRelativePath $dashboardRoot $buildLog
            $results.Add((Invoke-Step "Dashboard bundle budget" $dashboardRoot "node" @("scripts/check-bundle-budget.mjs", $relativeBuildLog) (& $log "dashboard-bundle-budget"))) | Out-Null
        }
        if ($IncludeE2E) {
            $results.Add((Invoke-Step "Dashboard Playwright" $dashboardRoot $pnpm @("exec", "playwright", "test") (& $log "dashboard-playwright"))) | Out-Null
        }
    }

    $failures = @($results | Where-Object { $_.ExitCode -ne 0 })
    $overall = if ($failures.Count -eq 0) { "PASS" } else { "FAIL" }

    if (-not $NoReport) {
        $reportPath = Join-Path $runDir "summary.md"
        $summary = New-Object System.Collections.Generic.List[string]
        $summary.Add("# Local PR gate - $overall")
        $summary.Add("")
        $summary.Add("- Generated UTC: $stamp")
        $summary.Add(('- Repo: ``{0}``' -f $RepoRoot))
        $summary.Add(('- Branch: ``{0}``' -f $branch))
        $summary.Add(('- HEAD: ``{0}``' -f $head))
        $summary.Add(('- Base: ``{0}`` / ``{1}``' -f $BaseRef, $base))
        $summary.Add(('- Scope: ``{0}``' -f $effectiveScope))
        if ($PrNumber -gt 0) { $summary.Add("- PR: #$PrNumber") }
        $summary.Add("")
        $summary.Add("## Results")
        $summary.Add("")
        $summary.Add("| Step | Status | Exit | Seconds | Log |")
        $summary.Add("|---|---:|---:|---:|---|")
        foreach ($result in $results) {
            $rel = (Get-LocalRelativePath $runDir $result.LogPath) -replace "\\", "/"
            $summary.Add("| $($result.Name) | $($result.Status) | $($result.ExitCode) | $($result.DurationSeconds) | [$rel]($rel) |")
        }
        $summary.Add("")
        $summary.Add("## Changed Files")
        $summary.Add("")
        if ($changed.Count -eq 0) {
            $summary.Add(('No changed files vs ``{0}``.' -f $BaseRef))
        }
        else {
            foreach ($file in $changed) { $summary.Add(('- ``{0}``' -f $file)) }
        }
        $summary.Add("")
        $summary.Add("## Git Status")
        $summary.Add("")
        $summary.Add('```text')
        foreach ($line in $statusLines) { $summary.Add($line) }
        $summary.Add('```')
        Set-Content -Path $reportPath -Value $summary -Encoding UTF8
        Write-Host ""
        Write-Host "[local-pr-gate] report: $reportPath"
    }

    Write-Host "[local-pr-gate] overall: $overall"
    if ($overall -eq "FAIL") { exit 1 }
    exit 0
}
finally {
    Pop-Location
}
