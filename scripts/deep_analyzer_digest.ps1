#requires -Version 5.1
$ErrorActionPreference = "Stop"
Start-Transcript -Path "$env:TEMP\deep_analyzer_digest.log" -Append

$repo   = "C:\Users\mattm\ThinkorSwim\jarvis-trader"
$python = "$repo\engine\.venv\Scripts\python.exe"
$db     = "$repo\engine\data\jarvis_trader.db"

Push-Location "$repo\engine"
& $python -c @"
from pathlib import Path
from discord.deep_analyzer.digest import render_and_dm

path = render_and_dm(
    db_path=Path(r'$db'),
    vault_root=Path.home() / 'my-vault',
)
print(f'digest written: {path}')
"@
Pop-Location

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: digest exited $LASTEXITCODE"
    Stop-Transcript
    exit 1
}

Stop-Transcript
