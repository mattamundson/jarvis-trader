# JARVIS Engine Watchdog
# Polls /health every 60s. Auto-restarts if unresponsive for 2 consecutive checks.
# Run once at startup; leave the window open or run minimized.
# Usage: powershell.exe -ExecutionPolicy Bypass -WindowStyle Minimized -File watchdog_engine.ps1

$healthUrl    = "http://localhost:8010/health"
$restartScript = "C:\Users\mattm\ThinkorSwim\jarvis-trader\restart_engine.ps1"
$pollSec      = 60      # seconds between checks
$maxFails     = 2       # consecutive failures before restart
$maxRestarts  = 5       # safety cap: stop after this many restarts in one session
$cooldownSec  = 30      # seconds to wait after restart before resuming checks

$failCount    = 0
$restartCount = 0

Write-Host "$(Get-Date -Format 'HH:mm:ss') JARVIS Watchdog started. Polling $healthUrl every ${pollSec}s."

while ($true) {
    Start-Sleep -Seconds $pollSec

    $ok = $false
    try {
        $r = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 8
        if ($r.StatusCode -eq 200) {
            $ok = $true
            if ($failCount -gt 0) {
                Write-Host "$(Get-Date -Format 'HH:mm:ss') Engine recovered after $failCount failed check(s)."
            }
            $failCount = 0
        }
    } catch {
        # timeout or connection refused
    }

    if (-not $ok) {
        $failCount++
        Write-Host "$(Get-Date -Format 'HH:mm:ss') Health check failed ($failCount/$maxFails): $healthUrl unreachable."

        if ($failCount -ge $maxFails) {
            if ($restartCount -ge $maxRestarts) {
                Write-Host "$(Get-Date -Format 'HH:mm:ss') WATCHDOG HALTED: $maxRestarts restarts reached. Manual intervention required."
                exit 1
            }

            $restartCount++
            Write-Host "$(Get-Date -Format 'HH:mm:ss') Triggering auto-restart #$restartCount..."

            try {
                & powershell.exe -ExecutionPolicy Bypass -File $restartScript 2>&1 | ForEach-Object { Write-Host "  [restart] $_" }
                Write-Host "$(Get-Date -Format 'HH:mm:ss') Restart script completed. Waiting ${cooldownSec}s before resuming checks."
            } catch {
                Write-Host "$(Get-Date -Format 'HH:mm:ss') Restart script failed: $($_.Exception.Message)"
            }

            $failCount = 0
            Start-Sleep -Seconds $cooldownSec
        }
    } else {
        Write-Host "$(Get-Date -Format 'HH:mm:ss') Engine OK (restart count: $restartCount)"
    }
}
