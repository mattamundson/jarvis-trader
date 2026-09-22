<#
.SYNOPSIS
  Smoke test for "Working TODAY" vertical slice (see docs/runbooks/WORKING_TODAY.md).

.DESCRIPTION
  1) GET  /health  (no API key — exempt)
  2) GET  /portfolio/paper/positions
  3) POST /portfolio/paper/trade  (open MCL paper line)
  4) GET  /portfolio/paper/positions  (read-back)

  Prerequisites: engine running on port 8010 (e.g. uvicorn main:app --port 8010 from engine/).

  Manual curl equivalents:
    curl -s http://127.0.0.1:8010/health
    curl -s -H "X-API-Key: YOUR_KEY" http://127.0.0.1:8010/portfolio/paper/positions
    curl -s -H "X-API-Key: YOUR_KEY" -H "Content-Type: application/json" ^
      -d "{\"action\":\"open\",\"symbol\":\"MCL\",\"side\":\"long\",\"quantity\":1,\"entry_price\":72.5,\"notes\":\"smoke_working_today\"}" ^
      http://127.0.0.1:8010/portfolio/paper/trade
#>
param(
    [string] $BaseUrl = "http://127.0.0.1:8010",
    [string] $ApiKey = [REDACTED]
)

$ErrorActionPreference = "Stop"

if (-not $ApiKey) {
    $envFile = Join-Path $PSScriptRoot "..\engine\.env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*API_KEY\s*=\s*(.+)\s*$') {
                $ApiKey = [REDACTED]'"').Trim("'")
                break
            }
        }
    }
    if (-not $ApiKey) {
        $ApiKey = "[REDACTED]"
    }
}

Write-Host "==> GET $BaseUrl/health"
$health = Invoke-RestMethod -Uri "$BaseUrl/health" -Method Get
$health | ConvertTo-Json -Depth 6
Write-Host ""

$headers = @{
    "X-API-Key" = $ApiKey
}

Write-Host "==> GET /portfolio/paper/positions (before)"
$before = Invoke-RestMethod -Uri "$BaseUrl/portfolio/paper/positions" -Headers $headers -Method Get
$before | ConvertTo-Json -Depth 6
Write-Host ""

$body = @{
    action       = "open"
    symbol       = "MCL"
    side         = "long"
    quantity     = 1
    entry_price  = 72.5
    notes        = "smoke_working_today"
} | ConvertTo-Json

Write-Host "==> POST /portfolio/paper/trade (open MCL)"
$open = Invoke-RestMethod -Uri "$BaseUrl/portfolio/paper/trade" -Headers $headers -Method Post -Body $body -ContentType "application/json"
$open | ConvertTo-Json -Depth 6
Write-Host ""

Write-Host "==> GET /portfolio/paper/positions (after)"
$after = Invoke-RestMethod -Uri "$BaseUrl/portfolio/paper/positions" -Headers $headers -Method Get
$after | ConvertTo-Json -Depth 6
Write-Host ""

if ($after.count -lt 1) {
    Write-Error "Smoke failed: expected at least one open position after POST."
}
Write-Host "Smoke Working TODAY: OK"
