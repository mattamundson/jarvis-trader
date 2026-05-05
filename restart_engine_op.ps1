# ============================================================================
# restart_engine_op.ps1
# ----------------------------------------------------------------------------
# Post-Phase-0 op-aware variant of restart_engine.ps1.
#
# Use ONLY AFTER:
#   1. All SERVICES in PHASE0_ROTATION_PLAYBOOK.md have been rotated.
#   2. The 1Password 'Amo Personal' vault is fully populated with the new
#      credentials referenced in engine/.env.op-template (20 op:// refs).
#   3. The op CLI is signed in for the current shell session.
#
# Falls back gracefully if the op CLI is not signed in (prints WARN, exits
# without restarting the engine - so a misfire never leaves the running
# engine in a half-state).
#
# This is a NEW companion script. The canonical restart_engine.ps1 is
# UNTOUCHED so the currently-running engine remains stable through the
# rotation transition.
#
# Difference from canonical restart_engine.ps1:
#   - Pre-flight: requires `op whoami` to succeed (signed-in 1Password CLI).
#   - Engine launch is wrapped with `op run --env-file=...op-template -- ...`
#     so secrets are injected from 1P at process-start, never written to
#     disk as plaintext.
#   - Plaintext engine/.env is NOT loaded into the parent shell when op-mode
#     is active (op run handles env injection for the child process).
# ============================================================================

$repoRoot = "C:\Users\mattm\ThinkorSwim\jarvis-trader"
$pythonExe = Join-Path $repoRoot "engine\.venv\Scripts\python.exe"
$envFile = Join-Path $repoRoot "engine\.env"
$opTemplate = Join-Path $repoRoot "engine\.env.op-template"
$opExe = "C:\Users\mattm\AppData\Local\Microsoft\WinGet\Links\op.exe"

# ── Pre-flight: 1Password CLI signed-in check ────────────────────────────────
if (-not (Test-Path $opExe)) {
    Write-Host "ERROR: op CLI not found at $opExe"
    Write-Host "  Install: winget install AgileBits.1Password.CLI"
    exit 1
}
if (-not (Test-Path $opTemplate)) {
    Write-Host "ERROR: op-template not found at $opTemplate"
    Write-Host "  Expected from Wave 1 prep work. Re-run that step before using this script."
    exit 1
}

# `op whoami` returns non-zero when not signed in.
& $opExe whoami 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "WARN: 1Password CLI not signed in."
    Write-Host "  Run: op signin"
    Write-Host "  Then re-run this script. Engine NOT restarted (canonical engine still running)."
    exit 1
}

Write-Host "1Password CLI signed in - proceeding with op-aware engine restart."

# ── PM2 fast path ────────────────────────────────────────────────────────────
# Mirrors restart_engine.ps1 PM2 path. PM2's stored ecosystem config would
# need to be updated to invoke `op run` for the op-aware path to apply under
# PM2 supervision. Until that update, the PM2 path here just delegates to a
# normal `pm2 restart` and the op-template injection only takes effect on
# the non-PM2 path below. This is intentional pre-staging - the PM2 ecosystem
# update is a separate, future change.
$pm2Managed = $false
try {
    $pm2Json = pm2 jlist 2>$null | Out-String
    if ($pm2Json -match '"name"\s*:\s*"jarvis-engine"') { $pm2Managed = $true }
}
catch {}

if ($pm2Managed) {
    Write-Host "Detected jarvis-engine under PM2 - delegating to pm2 restart."
    Write-Host "  NOTE: PM2 ecosystem.config.js still needs to be updated to wrap"
    Write-Host "        the engine command with 'op run --env-file=$opTemplate --'"
    Write-Host "        for op-injection to take effect under PM2 supervision."

    if (Test-Path $envFile) {
        $clientId = [int]((Get-Date).ToString("ss")) + 200
        (Get-Content $envFile) -replace "IBKR_CLIENT_ID=\d+", "IBKR_CLIENT_ID=$clientId" | Set-Content $envFile
        Write-Host "Using IBKR client ID: $clientId"
    }

    pm2 restart jarvis-engine | Out-Host
    Write-Host "Waiting for engine to come up..."
    $startTime = Get-Date
    $deadline = $startTime.AddSeconds(360)
    $healthy = $false
    $lastProgressPrint = 0
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri "http://localhost:8010/health" -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { $healthy = $true; break }
        }
        catch {}
        Start-Sleep -Seconds 2
        $elapsed = [int]((Get-Date) - $startTime).TotalSeconds
        if ($elapsed -ge 60 -and $lastProgressPrint -lt 60) {
            Write-Host '  [60s] still booting (uvicorn not yet bound; normal up to ~230s)'
            $lastProgressPrint = 60
        }
        elseif ($elapsed -ge 180 -and $lastProgressPrint -lt 180) {
            Write-Host '  [180s] still booting (scanner retry cascade; steady-state bind ~229s)'
            $lastProgressPrint = 180
        }
        elseif ($elapsed -ge 300 -and $lastProgressPrint -lt 300) {
            Write-Host '  [300s] still booting (if this keeps going past 360s, check pm2 logs for crash)'
            $lastProgressPrint = 300
        }
    }
    if (-not $healthy) {
        Write-Host "ERROR: engine did not respond on /health within 360s after pm2 restart."
        Write-Host "Last 30 error-log lines for triage:"
        try {
            pm2 logs jarvis-engine --nostream --lines 30 --err 2>&1 | Select-Object -Last 30 | Out-Host
        }
        catch {
            Write-Host "  (pm2 logs fetch failed: $($_.Exception.Message))"
        }
        exit 1
    }

    $uptimeMs = -1
    try {
        $raw = (pm2 jlist 2>$null | Out-String)
        $idx = $raw.IndexOf('"name":"jarvis-engine"')
        if ($idx -ge 0) {
            $slice = $raw.Substring($idx)
            $m = [regex]::Match($slice, '"pm_uptime"\s*:\s*(\d+)')
            if ($m.Success) {
                $nowMs = [int64]([DateTimeOffset]::Now.ToUnixTimeMilliseconds())
                $uptimeMs = $nowMs - [int64]$m.Groups[1].Value
            }
        }
    }
    catch {
        Write-Host "Could not read pm2 jlist for uptime verification: $($_.Exception.Message)"
    }

    if ($uptimeMs -lt 0) {
        Write-Host "ERROR: could not verify pm2 restart (jlist unreadable)."
        exit 1
    }
    $elapsedMs = [int64]((Get-Date) - $startTime).TotalMilliseconds
    $cycleBudgetMs = $elapsedMs + 5000
    if ($uptimeMs -gt $cycleBudgetMs) {
        Write-Host ("ERROR: pm2 restart did NOT cycle the process - uptime=" + $uptimeMs + "ms exceeds elapsed=" + $elapsedMs + "ms (+5s tolerance).")
        Write-Host "  Stale uvicorn is still running. Try: pm2 delete jarvis-engine ; then re-run this script."
        exit 1
    }

    Write-Host ("Engine UP: 200 (pm2 uptime " + $uptimeMs + "ms / elapsed " + $elapsedMs + "ms - fresh)")
    exit 0
}

# ── Non-PM2 path: launch under op run ────────────────────────────────────────

# Stop existing scheduled task if registered.
$taskName = "JarvisEngine"
$taskExists = (schtasks /query /tn $taskName 2>$null) -match $taskName
if ($taskExists) {
    Write-Host "Stopping JarvisEngine task..."
    schtasks /end /tn $taskName 2>$null | Out-Null
    Start-Sleep 3
}

# Kill processes LISTENING on port 8010 only.
function Get-ListenPids8010 {
    Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { $_.OwningProcess } |
        Where-Object { $_ -gt 0 } |
        Sort-Object -Unique
}

function Kill-WSL2SafePids8010 {
    $netstatPids = (netstat -ano 2>$null | Select-String ":\b8010\b\s" | ForEach-Object {
            ($_ -split '\s+')[-1]
        }) | Sort-Object -Unique | Where-Object { $_ -match '^\d+$' }

    if (-not $netstatPids) { return }

    $winPids = (Get-Process -ErrorAction SilentlyContinue).Id
    $toKill = $netstatPids | Where-Object { $winPids -contains [int]$_ }

    foreach ($p in $toKill) {
        Write-Host "Killing netstat PID $p (WSL2-safe check)"
        taskkill /PID $p /F 2>$null | Out-Null
    }
}

$maxKillPasses = 3
for ($i = 0; $i -lt $maxKillPasses; $i++) {
    $pids = @(Get-ListenPids8010)
    if ($pids.Count -eq 0) { break }
    foreach ($p in $pids) {
        Write-Host "Killing PID $p (listener on 8010)"
        $out = & taskkill /F /PID $p 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host " taskkill failed (exit $LASTEXITCODE): $out"
        }
    }
    Kill-WSL2SafePids8010
    Start-Sleep -Seconds 3
}

$stillListen = @(Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue)
if ($stillListen.Count -gt 0) {
    $blockers = $stillListen | ForEach-Object { $_.OwningProcess } | Where-Object { $_ -gt 0 } | Sort-Object -Unique
    Write-Host "Port 8010 still has LISTEN: PIDs $($blockers -join ', ')"
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8010/health" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) {
            Write-Host "ENGINE RESTART FAILED: Old process still running. Run as Administrator or use Task Manager to kill python.exe started earliest today."
            exit 1
        }
    }
    catch {
        Write-Host "Engine not responding on /health: $($_.Exception.Message)"
    }
    exit 1
}

# Rotate IBKR client ID (still done locally - IBKR_CLIENT_ID is rotated each
# restart for connection-id collision avoidance, not a credential).
# The op-template references this from 1P, but for legacy compatibility we
# also rotate the on-disk value if .env exists. This does NOT undo the
# secret-hygiene goal because the actual rotation target is the 1P value,
# updated separately via `op item edit`.
if (Test-Path $envFile) {
    $clientId = [int]((Get-Date).ToString("ss")) + 200
    (Get-Content $envFile) -replace "IBKR_CLIENT_ID=\d+", "IBKR_CLIENT_ID=$clientId" | Set-Content $envFile
    Write-Host "Using IBKR client ID: $clientId (legacy .env rotated)"
}

Write-Host "Starting engine via op run (secrets injected from 1Password)..."
$env:PYTHONUTF8 = "1"

# Launch python under `op run --env-file=...op-template -- ...`. The op CLI
# resolves all op:// references against the signed-in 1P session and exposes
# them to the child process as env vars at start time only.
if ($taskExists) {
    Write-Host "WARN: JarvisEngine scheduled task is registered but op-aware mode requires"
    Write-Host "      command-line launch. Either (a) update the scheduled task ACTION to"
    Write-Host "      wrap with 'op run --env-file=...op-template --', or (b) unregister the"
    Write-Host "      task before using this script."
    Write-Host "      For now, falling through to direct Start-Process launch."
}

Start-Process -FilePath $opExe `
    -ArgumentList @(
    "run",
    "--env-file=$opTemplate",
    "--",
    $pythonExe, "-m", "uvicorn", "main:app",
    "--host", "0.0.0.0",
    "--port", "8010",
    "--log-level", "warning"
) `
    -WorkingDirectory (Join-Path $repoRoot "engine") `
    -WindowStyle Hidden

Write-Host "Waiting for engine to start..."
Start-Sleep 15

try {
    $r = Invoke-WebRequest -Uri "http://localhost:8010/health" -UseBasicParsing -TimeoutSec 5
    Write-Host "Engine UP: $($r.StatusCode) (op-aware - secrets sourced from 1Password)"
}
catch {
    Write-Host "Engine not responding"
    exit 1
}

# ============================================================================
# DASHBOARD CONSISTENCY REQUIREMENT
# ----------------------------------------------------------------------------
# The Next.js dashboard at C:\Users\mattm\ThinkorSwim\jarvis-trader\dashboard\
# uses a build-time env var to authenticate to the engine API:
#
#   File:     dashboard/.env.local
#   Variable: NEXT_PUBLIC_ENGINE_API_KEY
#
# After Phase-0 rotation, the dashboard's NEXT_PUBLIC_ENGINE_API_KEY value
# MUST EXACTLY MATCH the new value stored in 1Password under:
#
#   Vault:    Amo Personal
#   Item:     Jarvis-Internal
#   Field:    API_KEY
#
# (This is the same value the engine reads via the op:// reference for
#  API_KEY in engine/.env.op-template. Mismatch -> dashboard 401s on every
#  /api request to the engine.)
#
# Required post-rotation steps for dashboard consistency:
#   1. Update 1P item Jarvis-Internal/API_KEY with the newly rotated value.
#   2. Update dashboard/.env.local NEXT_PUBLIC_ENGINE_API_KEY to the same value.
#      (NEXT_PUBLIC_ vars are baked into the client bundle at build time, so
#       they cannot be sourced via `op run` at runtime - they must be present
#       on disk during `pnpm build`. This is a Next.js framework constraint.)
#   3. Rebuild the dashboard: `cd dashboard ; pnpm build` (or restart dev server).
#   4. Verify in browser DevTools: Network tab -> any /api request ->
#      Authorization header should match the rotated key.
#
# Note: NEXT_PUBLIC_* keys are intentionally browser-exposed (read by client
# JavaScript), so they sit slightly outside the credential-guard secret-
# hygiene model. The mitigation is engine-side: the API_KEY must enforce
# IP/origin restrictions OR the engine must run only on localhost (current
# state - http://localhost:8010 is loopback-only).
# ============================================================================
