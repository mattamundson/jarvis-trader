<#
.SYNOPSIS
  Post-restart verification gate for the JARVIS engine after deploying the
  master-convergence (PR #75) + the forward-test / decision-identity spine.

.DESCRIPTION
  Run this AFTER restart_engine.ps1 returns (steady-state startup ~229s). It is
  fully READ-ONLY: it only GETs status endpoints and prints PASS/FAIL per gate.
  Exit code 0 == all hard gates passed; 1 == at least one hard gate failed.

  Field names are grounded in engine/routers/health_router.py (the real handler):
    status              "ok" iff db_ok AND llm_path_healthy   (line ~416)
    llm_path_healthy    bool                                   (line ~443)
    tradingview_mcp_healthy bool                               (line ~447)
    ibkr_data_connected bool                                   (line ~437)
    vertex_failover_count int                                  (line ~445)

  Notes:
    - Uses 127.0.0.1, never localhost (Windows IPv6 quirk).
    - Reads API_KEY from engine/.env and sends X-API-Key on every call
      (harmless on unauthenticated routes like /health).
    - IB data leg (ibkr_data_connected) is reported but NOT a hard gate: the
      reconnect is an Amo-gated action (POST /data/reconnect) and live port
      4001 is permanently blocked. TV MCP is the Tier-0 bar source.
#>
[CmdletBinding()]
param(
  [string]$BaseUrl = "http://127.0.0.1:8010",
  [string]$Symbol  = "MES"
)

$ErrorActionPreference = "Stop"
$script:HardFail = 0

# ---- read API_KEY from engine/.env (best-effort) -----------------------------
$ApiKey = $null
$envPath = Join-Path $PSScriptRoot "..\engine\.env"
if (Test-Path $envPath) {
  $line = Select-String -Path $envPath -Pattern '^\s*API_KEY\s*=' -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($line) { $ApiKey = ($line.Line -replace '^\s*API_KEY\s*=\s*', '').Trim().Trim('"').Trim("'") }
}
$Headers = @{}
if ($ApiKey) { $Headers["X-API-Key"] = $ApiKey }

function Get-Json([string]$Path) {
  try { return Invoke-RestMethod -Uri "$BaseUrl$Path" -Headers $Headers -TimeoutSec 15 }
  catch { return $null }
}

function Report([string]$Name, [bool]$Pass, [string]$Detail, [bool]$Hard = $true) {
  $tag = if ($Pass) { "PASS" } else { if ($Hard) { "FAIL" } else { "WARN" } }
  Write-Host ("[{0}] {1} -- {2}" -f $tag, $Name, $Detail)
  if (-not $Pass -and $Hard) { $script:HardFail++ }
}

Write-Host "=== JARVIS post-restart verification gate ($BaseUrl) ==="

# ---- GATE 1: /health core ----------------------------------------------------
$h = Get-Json "/health"
if ($null -eq $h) {
  Report "health.reachable" $false "GET /health did not return JSON (engine down or still starting -- restart_engine.ps1 ~229s steady state)"
} else {
  Report "health.status"            ($h.status -eq "ok")            "status=$($h.status)"
  Report "health.llm_path_healthy"  ([bool]$h.llm_path_healthy)     "llm_path_healthy=$($h.llm_path_healthy) vertex_failover_count=$($h.vertex_failover_count)"
  Report "health.tradingview_mcp"   ([bool]$h.tradingview_mcp_healthy) "tradingview_mcp_healthy=$($h.tradingview_mcp_healthy)"
  # IB data leg: reported, NOT a hard gate (Amo-gated reconnect; TV MCP is Tier-0).
  Report "health.ibkr_data_connected" ([bool]$h.ibkr_data_connected) "ibkr_data_connected=$($h.ibkr_data_connected) (reconnect is Amo-gated: POST /data/reconnect)" $false
}

# ---- GATE 2: /health/full (per-symbol freshness + provider state) ------------
$hf = Get-Json "/health/full"
if ($null -eq $hf) {
  Report "health_full.reachable" $false "GET /health/full did not return JSON" $false
} else {
  $ov = if ($hf.PSObject.Properties.Name -contains 'overall') { $hf.overall } else { $hf.status }
  Report "health_full.not_degraded" ($ov -ne "degraded") "overall=$ov" $false
}

# ---- GATE 3: /safety/status (kill switch inactive) ---------------------------
$s = Get-Json "/safety/status"
if ($null -eq $s) {
  Report "safety.reachable" $false "GET /safety/status did not return JSON"
} else {
  $killed = $false
  if ($s.PSObject.Properties.Name -contains 'is_killed') { $killed = [bool]$s.is_killed }
  elseif ($s.PSObject.Properties.Name -contains 'kill_switch_active') { $killed = [bool]$s.kill_switch_active }
  Report "safety.kill_switch_clear" (-not $killed) "is_killed=$killed daily_pnl=$($s.daily_realized_pnl) equity=$($s.current_equity)"
}

# ---- GATE 4: /brokers/positions (non-blind) ----------------------------------
$pos = Get-Json "/brokers/positions"
Report "brokers.positions_reachable" ($null -ne $pos) "endpoint returned $(if($null -ne $pos){'data'}else{'null (IB data leg may be down -- Amo reconnect)'} )" $false

# ---- GATE 5: forward-test status (proves the forward-test loop is live) -------
$ft = Get-Json "/forward-test/status?symbol=$Symbol"
Report "forward_test.status" ($null -ne $ft) "GET /forward-test/status?symbol=$Symbol -> $(if($null -ne $ft){'ok'}else{'null'})"

# ---- GATE 6: /analytics/forward-test lineages[] (decision-identity stamping) --
$aft = Get-Json "/analytics/forward-test"
if ($null -eq $aft) {
  Report "analytics.forward_test" $false "GET /analytics/forward-test did not return JSON" $false
} else {
  $hasLineages = $aft.PSObject.Properties.Name -contains 'lineages'
  Report "analytics.forward_test.lineages" $hasLineages "lineages block present=$hasLineages (proves decision-identity stamping landed)" $false
}

# ---- GATE 7: CONDITIONAL -- excursion (only if WS4 post-trade landed) ---------
$exc = Get-Json "/analytics/excursion"
if ($null -eq $exc) {
  Report "analytics.excursion(optional)" $false "endpoint absent or empty -- if WS4 landed, run engine/analytics/excursion_backfill.py once to populate" $false
} else {
  Report "analytics.excursion(optional)" $true "excursion endpoint live" $false
}

Write-Host ""
if ($script:HardFail -eq 0) {
  Write-Host "RESULT: all hard gates PASS. Deploy verified."
  exit 0
} else {
  Write-Host "RESULT: $script:HardFail hard gate(s) FAILED. Do NOT treat the deploy as verified."
  exit 1
}
