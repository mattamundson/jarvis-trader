
$repoRoot = "C:\Users\mattm\ThinkorSwim\jarvis-trader"
$pythonExe = Join-Path $repoRoot "engine\.venv\Scripts\python.exe"
$envFile = Join-Path $repoRoot "engine\.env"

# ── PM2 fast path ────────────────────────────────────────────────────────────
# If jarvis-engine is registered with PM2, delegate the restart to PM2 instead
# of racing our port-kill against PM2's auto-restart. History: when the two
# fight, PM2 sometimes wins the rebind and `Start-Process` silently exits,
# leaving the OLD uvicorn running (uptime does not reset, new code does not
# load). The port-based logic below is kept only for non-PM2 setups.
$pm2Managed = $false
try {
    $pm2Json = pm2 jlist 2>$null | Out-String
    if ($pm2Json -match '"name"\s*:\s*"jarvis-engine"') { $pm2Managed = $true }
} catch {}

if ($pm2Managed) {
    Write-Host "Detected jarvis-engine under PM2 - using pm2 restart (port-kill path skipped)"

    if (Test-Path $envFile) {
        $clientId = [int]((Get-Date).ToString("ss")) + 200
        (Get-Content $envFile) -replace "IBKR_CLIENT_ID=\d+", "IBKR_CLIENT_ID=$clientId" | Set-Content $envFile
        Write-Host "Using IBKR client ID: $clientId"
    }

    pm2 restart jarvis-engine | Out-Host
    Write-Host "Waiting for engine to come up..."
    # Poll /health with a 360s ceiling. Full startup (SafetyLayer, PnL,
    # RL model load, scheduler, IB init, scanner first-pass retry cascade)
    # was observed at 229s on 2026-04-21 after the advisor temperature fix
    # restart. Prior 180s ceiling produced a false-ERROR on a successful
    # boot because the scanner's TV-feed retries kept uvicorn from binding.
    $startTime = Get-Date
    $deadline  = $startTime.AddSeconds(360)
    $healthy   = $false
    $lastProgressPrint = 0
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri "http://localhost:8010/health" -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { $healthy = $true; break }
        } catch {}
        Start-Sleep -Seconds 2
        # Reassure operator at 60s / 180s / 300s marks — scanner first-pass
        # and RL model load can keep uvicorn from binding until ~230s.
        $elapsed = [int]((Get-Date) - $startTime).TotalSeconds
        if ($elapsed -ge 60 -and $lastProgressPrint -lt 60) {
            Write-Host '  [60s] still booting (uvicorn not yet bound; normal up to ~230s)'
            $lastProgressPrint = 60
        } elseif ($elapsed -ge 180 -and $lastProgressPrint -lt 180) {
            Write-Host '  [180s] still booting (scanner retry cascade; steady-state bind ~229s)'
            $lastProgressPrint = 180
        } elseif ($elapsed -ge 300 -and $lastProgressPrint -lt 300) {
            Write-Host '  [300s] still booting (if this keeps going past 360s, check pm2 logs for crash)'
            $lastProgressPrint = 300
        }
    }
    if (-not $healthy) {
        Write-Host "ERROR: engine did not respond on /health within 360s after pm2 restart."
        Write-Host "Last 30 error-log lines for triage:"
        try {
            pm2 logs jarvis-engine --nostream --lines 30 --err 2>&1 | Select-Object -Last 30 | Out-Host
        } catch {
            Write-Host "  (pm2 logs fetch failed: $($_.Exception.Message))"
        }
        exit 1
    }

    # Verify the cycle actually happened. PM2 has been observed no-op'ing on
    # transient conditions. A fresh restart's pm_uptime should be less than
    # the time we spent waiting — if uptime exceeds our elapsed script time,
    # the process started BEFORE this script ran, which means pm2 didn't cycle.
    # Parse pm_uptime via regex — ConvertFrom-Json trips over PM2's duplicate
    # case-insensitive env-var keys (USERNAME vs username) on Windows.
    $uptimeMs = -1
    try {
        $raw = (pm2 jlist 2>$null | Out-String)
        # Locate the jarvis-engine record and pull its pm_uptime number.
        $idx = $raw.IndexOf('"name":"jarvis-engine"')
        if ($idx -ge 0) {
            $slice = $raw.Substring($idx)
            $m = [regex]::Match($slice, '"pm_uptime"\s*:\s*(\d+)')
            if ($m.Success) {
                $nowMs = [int64]([DateTimeOffset]::Now.ToUnixTimeMilliseconds())
                $uptimeMs = $nowMs - [int64]$m.Groups[1].Value
            }
        }
    } catch {
        Write-Host "Could not read pm2 jlist for uptime verification: $($_.Exception.Message)"
    }

    if ($uptimeMs -lt 0) {
        Write-Host "ERROR: could not verify pm2 restart (jlist unreadable). Aborting so caller doesn't mistake this for success."
        exit 1
    }
    # Cycle detector: uptime must be <= elapsed-since-script-start (with 5s
    # clock-skew tolerance). Previous static 60000ms cutoff broke when real
    # startup grew past 60s — healthy restarts taking 197s were flagged as
    # stale because the cutoff was shorter than the successful bind time.
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

# ── Non-PM2 path: Task-Scheduler or plain uvicorn via Start-Process ──────────

# If the JarvisEngine scheduled task is registered, use it for clean stop/start.
$taskName = "JarvisEngine"
$taskExists = (schtasks /query /tn $taskName 2>$null) -match $taskName
if ($taskExists) {
    Write-Host "Stopping JarvisEngine task..."
    schtasks /end /tn $taskName 2>$null | Out-Null
    Start-Sleep 3
}

# Kill processes LISTENING on port 8010 only
function Get-ListenPids8010 {
    Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { $_.OwningProcess } |
        Where-Object { $_ -gt 0 } |
        Sort-Object -Unique
}

# WSL2 guard: netstat sometimes reports WSL2 port-forwarding entries with
# PIDs that don't exist as real Windows processes.  Cross-reference netstat
# against the live Windows process list and kill only the intersection.
function Kill-WSL2SafePids8010 {
    $netstatPids = (netstat -ano 2>$null | Select-String ":\b8010\b\s" | ForEach-Object {
        ($_ -split '\s+')[-1]
    }) | Sort-Object -Unique | Where-Object { $_ -match '^\d+$' }

    if (-not $netstatPids) { return }

    # Match any live Windows PID (not only python*) so listeners under other hosts still resolve.
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
    # Secondary WSL2-safe pass: kills any python PIDs that netstat sees on
    # port 8010 but Get-NetTCPConnection may have missed (port-forwarding).
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
            Write-Host "  → Right-click Task Manager → Run as Administrator → find python.exe → End Task → re-run this script."
            exit 1
        }
    } catch {
        Write-Host "Engine not responding on /health: $($_.Exception.Message)"
    }
    exit 1
}

# Rotate IBKR client ID
$clientId = [int]((Get-Date).ToString("ss")) + 200
(Get-Content $envFile) -replace "IBKR_CLIENT_ID=\d+", "IBKR_CLIENT_ID=$clientId" | Set-Content $envFile
Write-Host "Using IBKR client ID: $clientId"

Write-Host "Starting engine..."
$env:PYTHONUTF8 = "1"

# Load .env into current session so Start-Process inherits correct values.
# This overrides any stale system env vars (e.g., POLYGON_API_KEY=test, API_KEY=test-key).
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^([A-Z][A-Z0-9_]*)=(.*)$') {
            $k = $matches[1]; $v = $matches[2].Trim('"').Trim("'")
            Set-Item -Path "Env:\$k" -Value $v
        }
    }
}

if ($taskExists) {
    Write-Host "Starting via Task Scheduler (no admin required)..."
    schtasks /run /tn $taskName
} else {
    Start-Process -FilePath $pythonExe `
        -ArgumentList "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010", "--log-level", "warning" `
        -WorkingDirectory (Join-Path $repoRoot "engine") `
        -WindowStyle Hidden
}

Write-Host "Waiting for engine to start..."
Start-Sleep 15

try {
    $r = Invoke-WebRequest -Uri "http://localhost:8010/health" -UseBasicParsing -TimeoutSec 5
    Write-Host "Engine UP: $($r.StatusCode)"
} catch {
    Write-Host "Engine not responding"
    exit 1
}
