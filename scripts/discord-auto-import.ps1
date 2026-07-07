# discord-auto-import.ps1
# Exports recent Discord channel messages via DiscordChatExporter CLI,
# then runs the Python importer to ingest into jarvis_trader.db.
# Schedule via: Jarvis-DiscordAutoImport (see docs/setup-guides/)

# ---------------------------------------------------------------------------
# 1. Load DISCORD_TOKEN from engine/.env
# ---------------------------------------------------------------------------
$envFile = Join-Path $PSScriptRoot "..\engine\.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^([A-Z_][A-Z0-9_]*)=(.*)$') {
            $val = $Matches[2].Trim()
            $val = $val -replace '\s*#.*$', ''          # strip inline comments
            if ($val -match '^["\x27](.*)["\x27]$') { $val = $Matches[1] }  # strip surrounding quotes
            [System.Environment]::SetEnvironmentVariable($Matches[1], $val, 'Process')
        }
    }
}
$token = $env:DISCORD_TOKEN
if (-not $token) {
    Write-Error "DISCORD_TOKEN not set in engine/.env. See docs: https://github.com/Tyrrrz/DiscordChatExporter/wiki/Obtaining-Token"
    exit 1
}

# ---------------------------------------------------------------------------
# 2. Paths
# ---------------------------------------------------------------------------
# DCE resolution order:
#   1. Known WinGet package path (stable across upgrades, breaks if source re-registered)
#   2. winget list output parsing (survives source re-registration)
#   3. Get-Command PATH lookup (works if user added DCE to PATH manually)
$dceExe = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Tyrrrz.DiscordChatExporter.CLI_Microsoft.Winget.Source_8wekyb3d8bbwe\DiscordChatExporter.Cli.exe"
if (-not (Test-Path $dceExe)) {
    # Try winget list to resolve the current install path dynamically
    try {
        $wgOut = winget list --id Tyrrrz.DiscordChatExporter.CLI --accept-source-agreements 2>$null | Out-String
        if ($wgOut -match 'DiscordChatExporter') {
            $candidate = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" `
                -Filter "DiscordChatExporter.Cli.exe" -Recurse -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($candidate) { $dceExe = $candidate.FullName }
        }
    } catch { }
}
if (-not (Test-Path $dceExe)) {
    $fallback = Get-Command "DiscordChatExporter.Cli.exe" -ErrorAction SilentlyContinue
    if ($fallback) { $dceExe = $fallback.Source }
}
$exportDir = Join-Path $PSScriptRoot "..\discord-export"
$python    = Join-Path $PSScriptRoot "..\engine\.venv\Scripts\python.exe"
$logFile   = Join-Path $PSScriptRoot "..\logs\discord-import-$(Get-Date -Format 'yyyyMMdd').log"
$repoRoot  = Join-Path $PSScriptRoot ".."

if (-not (Test-Path $dceExe)) {
    Write-Error "DiscordChatExporter.Cli.exe not found at: $dceExe`nRe-install: winget install Tyrrrz.DiscordChatExporter.CLI"
    exit 1
}

# ---------------------------------------------------------------------------
# 3. Ensure directories exist
# ---------------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $exportDir | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $logFile) | Out-Null

# ---------------------------------------------------------------------------
# 4. Export each channel via DCE (incremental: last 2 days)
# ---------------------------------------------------------------------------
$afterDate = (Get-Date).AddDays(-2).ToString("yyyy-MM-dd")

# market-updates is the sole feed for CoreyCommentaryProcessor -- treated as
# P1. All other channels are best-effort.
$primaryChannel  = "806343100435660801"   # market-updates (Corey commentary)
$secondaryChannels = @(
    "1133508659993915492",  # indicator-alerts
    "1133171126751735879",  # proton-bot-alerts
    "1134346527096184914",  # es
    "1134346568317808710",  # nq
    "1134346604225241158",  # gc
    "1134346687519936596",  # cl
    "1139200691949273138",  # ym
    "1139199780321509416",  # rty
    "1134346637993594890",  # eurusd
    "1280340964061216843",  # btc
    "1134346719690240052",  # spy
    "1130292150962245642",  # trade-alerts
    "741484321142997086",   # general
    "1490851279180660819"   # jarvis-trader bookmarks
)

# Export-Channel: retries up to $MaxRetries times with $RetrySleepSec backoff.
# Returns $true on success, $false after all retries exhausted.
function Export-Channel {
    param(
        [string]$ChannelId,
        [int]$MaxRetries = 3,
        [int]$RetrySleepSec = 30
    )
    for ($attempt = 1; $attempt -le $MaxRetries; $attempt++) {
        & $dceExe export `
            --channel $ChannelId `
            --token $token `
            --format Json `
            --output $exportDir `
            --after $afterDate | ForEach-Object { Write-Host $_ }
        if ($LASTEXITCODE -eq 0) { return $true }
        if ($attempt -lt $MaxRetries) {
            Write-Warning "Channel $ChannelId export failed (attempt $attempt/$MaxRetries, exit $LASTEXITCODE) -- retrying in ${RetrySleepSec}s..."
            Start-Sleep $RetrySleepSec
        }
    }
    return $false
}

# P1: export market-updates -- hard fail if all retries exhausted
$primaryOk = Export-Channel -ChannelId $primaryChannel -MaxRetries 3 -RetrySleepSec 30
if (-not $primaryOk) {
    Write-Error "market-updates (P1) export failed after 3 attempts -- aborting. Commentary processor will not run."
    exit 1
}

# Secondary channels: best-effort, log failures but continue
$successCount = 1  # market-updates already counted
foreach ($channelId in $secondaryChannels) {
    $ok = Export-Channel -ChannelId $channelId -MaxRetries 2 -RetrySleepSec 15
    if ($ok) { $successCount++ }
    else { Write-Warning "Channel $channelId export failed after retries -- skipping" }
}

$total = 1 + $secondaryChannels.Count
Write-Host "DCE: $successCount/$total channels exported successfully"

# ---------------------------------------------------------------------------
# 5. Run Python importer with --trigger-commentary
# ---------------------------------------------------------------------------
Push-Location $repoRoot
& $python -m engine.discord.cli `
    --source $exportDir `
    --db "engine/data/jarvis_trader.db" `
    --trigger-commentary `
    2>&1 | Tee-Object -FilePath $logFile -Append
$exitCode = $LASTEXITCODE
Pop-Location
exit $exitCode
