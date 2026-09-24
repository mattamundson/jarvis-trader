# dce-nightly.ps1 — stable launcher for Python DCE runner.
# Real logic lives in scripts/dce_nightly_runner.py to avoid PowerShell 5.1
# quoting pitfalls. Tokens are never passed in argv; the runner sets
# DISCORD_TOKEN in the child process environment for DiscordChatExporter.

$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$Python = if ($env:JARVIS_ENGINE_PYTHON) { $env:JARVIS_ENGINE_PYTHON } else { Join-Path $RepoRoot 'engine\.venv\Scripts\python.exe' }
$Runner = Join-Path $RepoRoot 'scripts\dce_nightly_runner.py'

if (-not (Test-Path $Python)) {
    Write-Error "Python venv not found at $Python"
    exit 20
}
if (-not (Test-Path $Runner)) {
    Write-Error "DCE runner not found at $Runner"
    exit 20
}

& $Python $Runner
exit $LASTEXITCODE
