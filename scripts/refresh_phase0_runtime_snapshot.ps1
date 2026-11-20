<#
.SYNOPSIS
Refreshes the read-only JARVIS A-01 runtime truth snapshot artifact.

.DESCRIPTION
Runs scripts/phase0_runtime_truth_snapshot.py with --force, writes a redacted JSON
artifact, and appends a small operational log. This wrapper never accepts API keys
or broker identifiers as command-line parameters; the Python producer reads the
local engine/.env value directly when it needs an auth header for loopback probes.
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$EngineUrl = "http://127.0.0.1:8010",
    [string]$OutputPath,
    [string]$LogPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $OutputPath -or $OutputPath.Trim().Length -eq 0) {
    $OutputPath = Join-Path $RepoRoot "phase0_runtime_truth_snapshot.json"
}
if (-not $LogPath -or $LogPath.Trim().Length -eq 0) {
    $LogPath = Join-Path $RepoRoot "logs\phase0_runtime_truth_snapshot_refresh.log"
}

$Python = Join-Path $RepoRoot "engine\.venv\Scripts\python.exe"
$Producer = Join-Path $RepoRoot "scripts\phase0_runtime_truth_snapshot.py"
$LogDir = Split-Path -Parent $LogPath
if ($LogDir) {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
}

function Write-RefreshLog {
    param([string]$Message)
    $Stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    Add-Content -Path $LogPath -Value "[$Stamp] $Message" -Encoding UTF8
}

try {
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "Project Python not found: $Python"
    }
    if (-not (Test-Path -LiteralPath $Producer -PathType Leaf)) {
        throw "Snapshot producer not found: $Producer"
    }

    Write-RefreshLog "START repo=$RepoRoot output=$OutputPath engine=$EngineUrl"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONPATH = ""

    $Output = & $Python $Producer --engine-url $EngineUrl --output $OutputPath --force 2>&1
    $ExitCode = $LASTEXITCODE
    foreach ($Line in $Output) {
        Write-RefreshLog "producer: $Line"
    }
    if ($ExitCode -ne 0) {
        throw "Snapshot producer exited with code $ExitCode"
    }

    $Raw = Get-Content -LiteralPath $OutputPath -Raw -Encoding UTF8
    $Json = $Raw | ConvertFrom-Json
    if ($Json.artifact -ne "JARVIS_A01_RUNTIME_TRUTH_SNAPSHOT") {
        throw "Unexpected artifact marker in $OutputPath"
    }
    if ($Json.secrets_included -ne $false) {
        throw "Snapshot claims secrets_included is not false"
    }
    if (-not $Json.captured_at_utc) {
        throw "Snapshot missing captured_at_utc"
    }

    $Size = (Get-Item -LiteralPath $OutputPath).Length
    Write-RefreshLog "OK captured_at=$($Json.captured_at_utc) bytes=$Size"
    Write-Host "OK phase0 runtime truth snapshot refreshed: $OutputPath"
    Write-Host "captured_at_utc=$($Json.captured_at_utc)"
    exit 0
}
catch {
    Write-RefreshLog "ERROR $($_.Exception.Message)"
    Write-Error $_.Exception.Message
    exit 1
}
