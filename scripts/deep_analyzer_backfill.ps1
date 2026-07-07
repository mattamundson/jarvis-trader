#requires -Version 5.1
param(
    [int]$BatchSize = 10,
    [int]$MaxBatches = 200,
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
Start-Transcript -Path "$env:TEMP\deep_analyzer_backfill.log" -Append

$repo   = "C:\Users\mattm\ThinkorSwim\jarvis-trader"
$python = "$repo\engine\.venv\Scripts\python.exe"
$db     = "$repo\engine\data\jarvis_trader.db"

# 1. Pause the live loop
Write-Host "Disabling JarvisTrader_DiscordDeepAnalyzer..."
schtasks /Change /TN JarvisTrader_DiscordDeepAnalyzer /DISABLE | Out-Null

# 2. Pre-count
Push-Location "$repo\engine"
$unanalyzed = & $python -c "import sqlite3; c=sqlite3.connect(r'$db'); print(c.execute('SELECT COUNT(*) FROM discord_bookmarks WHERE analyzed_at IS NULL').fetchone()[0])"
Write-Host "Unanalyzed rows: $unanalyzed"

if ($DryRun) {
    Write-Host "DryRun -- re-enabling loop and exiting."
    schtasks /Change /TN JarvisTrader_DiscordDeepAnalyzer /ENABLE | Out-Null
    Pop-Location
    Stop-Transcript
    exit 0
}

# 3. Drain
for ($i = 0; $i -lt $MaxBatches; $i++) {
    $n = & $python -c @"
import asyncio
from pathlib import Path
from discord.deep_analyzer.runner import run_once
async def main():
    n = await run_once(
        db_path=Path(r'$db'),
        vault_root=Path.home() / 'my-vault',
        limit=$BatchSize,
    )
    print(n)
asyncio.run(main())
"@
    Write-Host "batch $i wrote $n"
    if ([int]$n -eq 0) { break }
}

# 4. Re-enable the live loop
Write-Host "Re-enabling JarvisTrader_DiscordDeepAnalyzer..."
schtasks /Change /TN JarvisTrader_DiscordDeepAnalyzer /ENABLE | Out-Null

# 5. Final tally
& $python -c "import sqlite3; c=sqlite3.connect(r'$db'); print('remaining unanalyzed:', c.execute('SELECT COUNT(*) FROM discord_bookmarks WHERE analyzed_at IS NULL').fetchone()[0])"

Pop-Location
Stop-Transcript
