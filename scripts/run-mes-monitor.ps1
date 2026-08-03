# MES 24x7 Monitor Scheduler
# Runs the monitor on a fixed cadence during configured RTH hours.
# This script only produces suggestions; it does not place orders.

param(
  [string]$EngineDir = "C:\Users\mattm\master-jarvis\jarvis-trader\engine",
  [string]$Python = "engine/.venv/Scripts/python.exe",
  [string]$Script = "engine/monitors/mes_monitor_orchestrator.py",
  [string]$Config = "engine/config/mes_monitor_config.yaml",
  [switch]$DryRun
)

Set-Location "C:\Users\mattm\master-jarvis\jarvis-trader"

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $Python)) {
  Write-Error "Python venv not found at $Python"
  exit 1
}

if ($DryRun) {
  Write-Host "[dry-run] Would run: $Python $Script --config $Config"
  exit 0
}

# TODO: Replace this with actual candle ingestion from IBKR/TradingView.
# For now, this is a placeholder command.
& $Python $Script --config $Config
exit $LASTEXITCODE
