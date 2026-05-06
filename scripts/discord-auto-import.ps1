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
        if ($_ -match '^([A-Z_]+)=(.+)$') {
            [System.Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
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
# DCE installed via: winget install Tyrrrz.DiscordChatExporter.CLI
# WinGet package path — stable across minor DCE updates (package dir won't change)
$dceExe    = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Tyrrrz.DiscordChatExporter.CLI_Microsoft.Winget.Source_8wekyb3d8bbwe\DiscordChatExporter.Cli.exe"
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

$channels = @(
    "806343100435660801",   # market-updates (Corey commentary — PRIMARY)
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

foreach ($channelId in $channels) {
    & $dceExe export `
        --channel $channelId `
        --token $token `
        --format Json `
        --output $exportDir `
        --after $afterDate `
        --overwrite
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "DCE export failed for channel $channelId (exit $LASTEXITCODE)"
    }
}

# ---------------------------------------------------------------------------
# 5. Run Python importer with --trigger-commentary
# ---------------------------------------------------------------------------
Push-Location $repoRoot
& $python -m engine.discord.cli `
    --source $exportDir `
    --db "data/jarvis_trader.db" `
    --trigger-commentary `
    2>&1 | Tee-Object -FilePath $logFile -Append
$exitCode = $LASTEXITCODE
Pop-Location
exit $exitCode
