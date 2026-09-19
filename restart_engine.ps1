[CmdletBinding()]
param(
    # Escape hatch: force the non-PM2 port path even when the PM2 probe is
    # inconclusive (see the bounded-detection block below).
    [switch]$AssumeUnmanaged
)

$repoRoot = "C:\Users\mattm\ThinkorSwim\jarvis-trader"
$pythonExe = Join-Path $repoRoot "engine\.venv\Scripts\python.exe"
$envFile = Join-Path $repoRoot "engine\.env"

# ── PM2 fast path ────────────────────────────────────────────────────────────
# If jarvis-engine is registered with PM2, delegate the restart to PM2 instead
# of racing our port-kill against PM2's auto-restart. History: when the two
# fight, PM2 sometimes wins the rebind and `Start-Process` silently exits,
# leaving the OLD uvicorn running (uptime does not reset, new code does not
# load). The port-based logic below is kept only for non-PM2 setups.
#
# BOUNDED DETECTION (2026-09-19). The previous detection was an unbounded
# `pm2 jlist | Out-String` pipeline. `pm2 jlist` shells out to pidusage ->
# WMI (Get-CimInstance/gwmi), and when the host WMI repository hangs jlist
# never returns. Measured live 2026-09-19 01:30-01:33 CDT:
#   * `pm2 ping`                 -> pong in 0.2s
#   * `pm2 jlist` (bounded 45s)  -> TIMEOUT (unbounded: hangs indefinitely)
#   * `Get-CimInstance Win32_Process` (bounded 45s) -> TIMEOUT
# The unbounded pipeline therefore hung this entire restart script, i.e. the
# recovery path was unavailable exactly when it was needed (this is the same
# ".CMD launcher leaves children holding the pipe" class as the hermes doctor
# npm-audit deadlock fixed 2026-09-04).
#
# New behaviour: bounded attempts, then a LOUD, NON-DESTRUCTIVE abort (exit 6).
# We deliberately do NOT fall through to the port-kill path on a wedge -- that
# path kills whatever holds :8010, which during an RPC wedge is the live
# healthy engine. Use -AssumeUnmanaged to opt into the port path explicitly.
$Pm2JlistTimeoutSec = 20
$Pm2JlistAttempts = 2

$pm2Exe = $null
try {
    $pm2Cmd = Get-Command pm2 -ErrorAction SilentlyContinue
    if ($pm2Cmd) { $pm2Exe = $pm2Cmd.Source }
}
catch {}
if (-not $pm2Exe) {
    $pnpmPm2 = Join-Path $env:LOCALAPPDATA 'pnpm\pm2.CMD'
    if (Test-Path $pnpmPm2) { $pm2Exe = $pnpmPm2 }
}

function Invoke-BoundedPm2Jlist {
    param([int]$TimeoutSec = 20)
    $proc = $null
    $outTask = $null
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        # pm2 on this host is a .CMD shim (pnpm). CreateProcess cannot start a
        # .cmd directly, so route through cmd.exe. UseShellExecute stays false
        # so the output handles stay redirectable and the tree stays killable.
        $psi.FileName = $env:ComSpec
        $psi.Arguments = "/d /s /c `"`"$pm2Exe`" jlist`""
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.CreateNoWindow = $true
        $proc = New-Object System.Diagnostics.Process
        $proc.StartInfo = $psi
        [void]$proc.Start()
        $outTask = $proc.StandardOutput.ReadToEndAsync()
        [void]$proc.StandardError.ReadToEndAsync()
        if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
            return @{ ok = $false; reason = "timeout after ${TimeoutSec}s"; output = '' }
        }
        return @{ ok = $true; reason = 'ok'; output = $outTask.Result }
    }
    catch {
        return @{ ok = $false; reason = "error: $($_.Exception.Message)"; output = '' }
    }
    finally {
        if ($null -ne $proc) {
            try {
                if (-not $proc.HasExited) {
                    # Kill the whole launcher tree; pm2.CMD spawns node.exe
                    # children that keep the redirected pipe handles open.
                    taskkill /F /T /PID $proc.Id 2>$null | Out-Null
                }
            }
            catch {}
            try { $proc.Dispose() } catch {}
        }
    }
}

$pm2Managed = $false
if ($pm2Exe) {
    $pm2Detect = $null
    for ($attempt = 1; $attempt -le $Pm2JlistAttempts; $attempt++) {
        $pm2Detect = Invoke-BoundedPm2Jlist -TimeoutSec $Pm2JlistTimeoutSec
        if ($pm2Detect.ok) { break }
        if ($attempt -lt $Pm2JlistAttempts) { Start-Sleep -Seconds 2 }
    }

    if ($pm2Detect.ok) {
        if ($pm2Detect.output -match '"name"\s*:\s*"jarvis-engine"') { $pm2Managed = $true }
    }
    else {
        Write-Host "ERROR: 'pm2 jlist' did not complete after $Pm2JlistAttempts bounded attempt(s) of ${Pm2JlistTimeoutSec}s ($($pm2Detect.reason))."
        Write-Host "       PM2's RPC is wedged -- typically a hung WMI repository: 'pm2 ping' still answers pong while 'pm2 jlist'/pidusage hangs."
        Write-Host "       Refusing to continue: the non-PM2 port-kill fallback would kill the live engine holding :8010."
        Write-Host "       Diagnose / repair (repair needs an elevated shell):"
        Write-Host "         pm2 ping                  # expect pong"
        Write-Host "         winmgmt /verifyrepository # expect 'consistent'"
        Write-Host "         winmgmt /salvagerepository"
        Write-Host "       Or re-run  restart_engine.ps1 -AssumeUnmanaged  to force the port path."
        if (-not $AssumeUnmanaged) {
            exit 6
        }
        Write-Host "WARNING: -AssumeUnmanaged set -- proceeding down the non-PM2 port path despite the wedge."
        $pm2Managed = $false
    }
}

if ($pm2Managed) {
    Write-Host "Detected jarvis-engine under PM2 - using pm2 restart (port-kill path skipped)"

    if (Test-Path $envFile) {
        $clientId = [int]((Get-Date).ToString("ss")) + 200
        (Get-Content $envFile) -replace "IBKR_CLIENT_ID=\d+", "IBKR_CLIENT_ID=$clientId" | Set-Content $envFile
        Write-Host "Using IBKR client ID: $clientId"
    }

    # Load .env into current shell so PM2 --update-env picks up any changes
    # (e.g. ALLOW_PAPER_SIMULATED_ORDERS, READINESS_EDGE_MODE).  Without this,
    # plain 'pm2 restart' serves PM2's cached env from the original pm2 start.
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^([A-Z][A-Z0-9_]*)=(.*)$') {
                $k = $matches[1]; $v = $matches[2].Trim('"').Trim("'")
                Set-Item -Path "Env:\$k" -Value $v
            }
        }
    }

    pm2 restart jarvis-engine --update-env | Out-Host
    Write-Host "Waiting for engine to come up..."
    # Poll /health with a 480s ceiling. Full startup (SafetyLayer, PnL,
    # RL model load, scheduler, IB init, scanner first-pass retry cascade)
    # was observed at 229s on 2026-04-21 after the advisor temperature fix
    # restart and at ~401s on 2026-05-07 due to a slow Polygon WS handshake.
    # Prior 360s ceiling was tight; bumped to 480s to handle Polygon latency.
    $startTime = Get-Date
    $deadline = $startTime.AddSeconds(480)
    $healthy = $false
    $lastProgressPrint = 0
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:8010/health" -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { $healthy = $true; break }
        }
        catch {}
        Start-Sleep -Seconds 2
        # Reassure operator at 60s / 240s / 420s marks — scanner first-pass
        # and RL model load can keep uvicorn from binding until ~230s;
        # Polygon WS handshake can extend to ~400s in degraded conditions.
        $elapsed = [int]((Get-Date) - $startTime).TotalSeconds
        if ($elapsed -ge 60 -and $lastProgressPrint -lt 60) {
            Write-Host '  [60s] still booting (uvicorn not yet bound; normal up to ~230s)'
            $lastProgressPrint = 60
        }
        elseif ($elapsed -ge 240 -and $lastProgressPrint -lt 240) {
            Write-Host '  [240s] still booting (scanner retry cascade or Polygon WS handshake)'
            $lastProgressPrint = 240
        }
        elseif ($elapsed -ge 420 -and $lastProgressPrint -lt 420) {
            Write-Host '  [420s] still booting (if this keeps going past 480s, check pm2 logs for crash)'
            $lastProgressPrint = 420
        }
    }
    if (-not $healthy) {
        Write-Host "ERROR: engine did not respond on /health within 480s after pm2 restart."
        Write-Host "Last 30 error-log lines for triage:"
        try {
            pm2 logs jarvis-engine --nostream --lines 30 --err 2>&1 | Select-Object -Last 30 | Out-Host
        }
        catch {
            Write-Host "  (pm2 logs fetch failed: $($_.Exception.Message))"
        }
        exit 1
    }

    # Advisory pm2 cycle check — informational only.
    #
    # History: this block previously exit-1'd whenever the pm_uptime regex
    # appeared to exceed the elapsed-script time, on the theory that a fresh
    # restart's uptime should be < script wall time + a 5s skew tolerance.
    # In practice the comparison consistently false-positived (verified twice
    # in 24h, 2026-05-06 + 2026-05-07) on restarts /health had already
    # confirmed clean. Likely causes:
    #   - pm2 jlist reads the prior process record on the brief window
    #     between SIGKILL of the old worker and ts-update of the new one
    #   - `pm2 restart` returns asynchronously; the regex captures a
    #     monotonic-clock pm_uptime that doesn't always reset relative to
    #     wall-clock at the moment of polling
    # /health is the canonical pass/fail signal. If we got here, the engine
    # answered 200 within 480s, which is sufficient. Surface the uptime as
    # a warning when it looks suspicious; never block on it.
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
        Write-Host "WARN: could not read pm2 jlist for uptime advisory: $($_.Exception.Message)"
    }

    $elapsedMs = [int64]((Get-Date) - $startTime).TotalMilliseconds
    $cycleBudgetMs = $elapsedMs + 5000

    if ($uptimeMs -lt 0) {
        Write-Host "WARN: pm2 jlist unreadable; relying on /health for canonical status."
    }
    elseif ($uptimeMs -gt $cycleBudgetMs) {
        Write-Host ("WARN: pm2 uptime regex inconclusive (got " + $uptimeMs + "ms vs elapsed " + $elapsedMs + "ms); falling through to /health polling for canonical status.")
        Write-Host ("  /health returned 200 within 480s, so the engine is up. If you suspect a stale uvicorn, run: pm2 delete jarvis-engine ; .\restart_engine.ps1")
    }
    else {
        Write-Host ("Engine UP: 200 (pm2 uptime " + $uptimeMs + "ms / elapsed " + $elapsedMs + "ms - fresh)")
        exit 0
    }

    Write-Host "Engine UP: 200 (/health canonical; pm2 uptime advisory only)"
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
    }
    catch {
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
$env:PYTHONNOUSERSITE = "1"
# Hermes/Desktop shells can leak their own venv/PYTHONPATH into Start-Process.
# If inherited, engine\.venv\python.exe may import Hermes-site packages against
# a different stdlib and crash with `AssertionError: SRE module mismatch` before
# uvicorn binds. Clear interpreter-selection vars before loading engine .env.
Remove-Item Env:\PYTHONHOME -ErrorAction SilentlyContinue
Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
Remove-Item Env:\VIRTUAL_ENV -ErrorAction SilentlyContinue

# Load .env into current session so Start-Process inherits correct values.

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
}
else {
    # Capture stdout/stderr so import-time crashes (e.g. NameError on a missing
    # response_model class) leave a trail. Without redirection, -WindowStyle
    # Hidden swallowed the 2026-05-05 CircuitBreakerStatus NameError silently —
    # /health stayed unreachable while the only signal was a missing process.
    $bootLog = Join-Path $repoRoot "engine\logs\engine-boot.log"
    $bootErrLog = Join-Path $repoRoot "engine\logs\engine-boot-error.log"
    Start-Process -FilePath $pythonExe `
        -ArgumentList "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010", "--log-level", "warning" `
        -WorkingDirectory (Join-Path $repoRoot "engine") `
        -RedirectStandardOutput $bootLog `
        -RedirectStandardError  $bootErrLog `
        -WindowStyle Hidden
}

Write-Host "Waiting for engine to start..."
# Poll /health for up to 480s — matches the PM2-path ceiling. Non-PM2 starts
# via task scheduler or direct Start-Process both boot asynchronously; the
# 15s sleep used previously would always time-out on a 229s typical startup.
$startTime2 = Get-Date
$deadline2 = $startTime2.AddSeconds(480)
$healthy2 = $false
$lastProgressPrint2 = 0
while ((Get-Date) -lt $deadline2) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8010/health" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $healthy2 = $true; break }
    }
    catch {}
    Start-Sleep -Seconds 2
    $elapsed2 = [int]((Get-Date) - $startTime2).TotalSeconds
    if ($elapsed2 -ge 60 -and $lastProgressPrint2 -lt 60) {
        Write-Host "  [60s] still booting (normal up to ~230s)"
        $lastProgressPrint2 = 60
    }
    elseif ($elapsed2 -ge 240 -and $lastProgressPrint2 -lt 240) {
        Write-Host "  [240s] still booting (scanner retry or Polygon WS)"
        $lastProgressPrint2 = 240
    }
    elseif ($elapsed2 -ge 420 -and $lastProgressPrint2 -lt 420) {
        Write-Host "  [420s] still booting (check engine-boot-error.log for crash)"
        $lastProgressPrint2 = 420
    }
}
if (-not $healthy2) {
    Write-Host "ERROR: engine did not respond on /health within 480s."
    $bootErrLog2 = Join-Path $repoRoot "engine\logs\engine-boot-error.log"
    if (Test-Path $bootErrLog2) {
        Write-Host "Last 20 lines of engine-boot-error.log:"
        Get-Content $bootErrLog2 -Tail 20 | Out-Host
    }
    exit 1
}
Write-Host "Engine UP: 200 (/health)"
