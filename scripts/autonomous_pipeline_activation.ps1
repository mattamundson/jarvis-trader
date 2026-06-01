# autonomous_pipeline_activation.ps1
# DO NOT auto-run — Amo's hand only.
#
# Pre-flight ran 2026-05-21 — see verdict at:
#   second-brain/raw/_session-2026-05-21-amo/wiki/system/autonomous-scheduler-activation-prep.md
#
# Verdict: WAIT — ibkr_data_connected=false at time of check; see report for full matrix.
# Activation is safe once IB data reconnects. No code changes required before flip.
#
# Usage:
#   Read the pre-flight report first.
#   Manually add ENABLE_AUTONOMOUS_PIPELINE=1 to engine/.env (Step 1).
#   Then paste this script to restart and verify.
#
# Environment variables you may want to tune in engine/.env before restart:
#   ENABLE_AUTONOMOUS_PIPELINE=1                  # REQUIRED to enable
#   AUTONOMOUS_TICK_SECONDS=300                   # default 300 (5 min) — change if desired
#   AUTONOMOUS_CONFIDENCE_THRESHOLD=0.65          # default 0.65
#   AUTONOMOUS_CANDIDATE_TTL_SECONDS=1800         # default 1800 (30 min)
#   AUTONOMOUS_ACTIVE_SYMBOLS=MCL,MNQ             # default MCL,MNQ
#                                                  # NOTE: FUTURES_WATCHLIST=MES,MGC in .env —
#                                                  # autonomous symbols are INDEPENDENT of watchlist.
#                                                  # Confirm MCL,MNQ are the intended scan targets.

Set-Location "C:\Users\mattm\ThinkorSwim\jarvis-trader"

# Step 0: Confirm the flag is set before restarting
$flagLine = Select-String -Path "engine\.env" -Pattern "^ENABLE_AUTONOMOUS_PIPELINE=1" | Select-Object -First 1
if (-not $flagLine) {
    Write-Host "[ABORT] ENABLE_AUTONOMOUS_PIPELINE=1 not found in engine/.env"
    Write-Host "Add the line to engine/.env first, then re-run this script."
    exit 1
}
Write-Host "[OK] Flag confirmed in engine/.env: $($flagLine.Line)"

# Step 1: Read API key from .env (never hardcoded)
$rawKey = Select-String -Path "engine\.env" -Pattern "^API_KEY=" | Select-Object -First 1
if (-not $rawKey) {
    Write-Host "[ERROR] API_KEY not found in engine/.env"
    exit 1
}
$key = ($rawKey.Line -replace "^API_KEY=").Trim()
$headers = @{"X-API-Key" = $key}

# Step 2: Pre-restart safety snapshot
Write-Host "`n[PRE-RESTART] Current /health:"
try {
    $pre = Invoke-RestMethod "http://127.0.0.1:8010/health" -Headers $headers -TimeoutSec 10
    Write-Host "  status=$($pre.status) kill_switch=$($pre.kill_switch_active) live_trading=$($pre.live_trading) uptime=$([math]::Round($pre.uptime_seconds/60,1))min"
} catch {
    Write-Host "  Engine not responding — proceed with restart anyway"
}

# Step 3: Restart engine
Write-Host "`n[STEP 3] Restarting engine..."
.\restart_engine.ps1

# Step 4: Confirm health post-restart (restart_engine.ps1 polls, but double-check)
Write-Host "`n[STEP 4] Confirming /health post-restart..."
try {
    $post = Invoke-RestMethod "http://127.0.0.1:8010/health" -Headers $headers -TimeoutSec 30
    $lines = @(
        "  status             = $($post.status)",
        "  kill_switch_active = $($post.kill_switch_active)",
        "  live_trading       = $($post.live_trading)",
        "  paper_mode         = $($post.paper_mode)",
        "  ibkr_exec          = $($post.ibkr_execution_connected)",
        "  ibkr_data          = $($post.ibkr_data_connected)",
        "  llm_healthy        = $($post.llm_path_healthy)",
        "  tv_mcp_healthy     = $($post.tradingview_mcp_healthy)",
        "  uptime             = $([math]::Round($post.uptime_seconds,1))s"
    )
    $lines | Write-Host

    if ($post.status -ne "ok") {
        Write-Host "[WARN] Engine status is not 'ok' — check logs before proceeding."
    } elseif ($post.kill_switch_active) {
        Write-Host "[WARN] Kill switch is ACTIVE — autonomous scheduler will refuse every tick until deactivated."
    } else {
        Write-Host "[OK] Engine healthy. Autonomous scheduler loop should start within 60s."
    }
} catch {
    Write-Host "[ERROR] /health failed post-restart: $($_.Exception.Message)"
    Write-Host "Check pm2 logs: pm2 logs jarvis-engine --lines 50"
    exit 1
}

# Step 5: Look for the loop-started log line (wait up to 90s)
Write-Host "`n[STEP 5] Waiting up to 90s for autonomous loop confirmation..."
$loopStarted = $false
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    $logLines = pm2 logs jarvis-engine --lines 100 --nocolor 2>$null
    if ($logLines -match "Autonomous pipeline loop started|ENABLE_AUTONOMOUS_PIPELINE=1 detected at boot") {
        Write-Host "[OK] Autonomous loop confirmed started."
        $loopStarted = $true
        break
    }
    Start-Sleep 5
}
if (-not $loopStarted) {
    Write-Host "[WARN] Log confirmation not found within 90s."
    Write-Host "       Check: pm2 logs jarvis-engine --lines 200"
    Write-Host "       The loop may still be starting if the engine startup is slow."
}

# Step 6: First tick verification (wait one tick interval, default 300s)
Write-Host "`n[STEP 6] First-tick check in 300s (default tick interval)."
Write-Host "         You can check manually at any time:"
Write-Host "         Invoke-RestMethod 'http://127.0.0.1:8010/approvals/pending' -Headers @{'X-API-Key'='$key'}"
Write-Host ""
Write-Host "Waiting 300s for first tick..."
Start-Sleep 300

Write-Host "`n[STEP 6] /approvals/pending after first tick:"
try {
    $pending = Invoke-RestMethod "http://127.0.0.1:8010/approvals/pending" -Headers $headers -TimeoutSec 15
    Write-Host "  count=$($pending.count)"
    if ($pending.count -eq 0) {
        Write-Host "  (No candidates above threshold — this is normal if market is closed or confidence < 0.65)"
    } else {
        Write-Host "  Candidates enqueued:"
        $pending.candidates | ForEach-Object {
            Write-Host "    id=$($_.id) $($_.symbol) $($_.direction) conf=$($_.confidence) expires=$($_.expires_at)"
        }
        Write-Host "`n  To approve: POST /approvals/{id}/approve"
        Write-Host "  To reject:  POST /approvals/{id}/reject"
    }
} catch {
    Write-Host "[ERROR] $($_.Exception.Message)"
}

Write-Host "`n[DONE] Autonomous pipeline activation complete."
Write-Host "       Deactivate at any time: set ENABLE_AUTONOMOUS_PIPELINE=0 in engine/.env + restart."
Write-Host "       Pending candidates auto-expire on TTL (default 30 min) — none auto-execute."
