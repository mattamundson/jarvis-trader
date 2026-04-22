# JARVIS Trader Startup
$repoRoot = "C:\Users\mattm\ThinkorSwim\jarvis-trader"
$engineDir = Join-Path $repoRoot "engine"
$python = Join-Path $engineDir ".venv\Scripts\python.exe"

Set-Location $repoRoot
$env:PYTHONUTF8 = "1"

# Run from engine/ directory so internal imports (from agents.X) resolve correctly
Start-Process -FilePath $python `
    -ArgumentList "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010" `
    -WorkingDirectory $engineDir `
    -WindowStyle Normal

Write-Host "Engine starting on port 8010..." -ForegroundColor Cyan