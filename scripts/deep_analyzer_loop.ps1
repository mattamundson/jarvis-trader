#requires -Version 5.1
$ErrorActionPreference = "Stop"
Start-Transcript -Path "$env:TEMP\deep_analyzer_loop.log" -Append

$repo   = "C:\Users\mattm\ThinkorSwim\jarvis-trader"
$python = "$repo\engine\.venv\Scripts\python.exe"
$db     = "$repo\engine\data\jarvis_trader.db"

Push-Location "$repo\engine"
& $python -c @"
import asyncio
from pathlib import Path
from discord.deep_analyzer.runner import run_once

async def main():
    n = await run_once(
        db_path=Path(r'$db'),
        vault_root=Path.home() / 'my-vault',
        limit=5,
    )
    print(f'wrote {n}')

asyncio.run(main())
"@
Pop-Location

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: runner exited $LASTEXITCODE"
    Stop-Transcript
    exit 1
}

Stop-Transcript
