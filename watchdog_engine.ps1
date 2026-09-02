# =============================================================================
# JARVIS Engine Watchdog
# =============================================================================
# Monitors http://localhost:8010/health every 60 seconds.
# Restarts the engine if health fails 3 consecutive times (~3 minutes down).
# Sends WhatsApp alert via OpenClaw if auto-restart fails.
# Logs all events to watchdog.log with automatic 10MB rotation.
# 
# DO NOT restart if ibkr_connected=false — that's an IB Gateway outage, not a crash.
# Only restart if: status != "ok" OR HTTP timeout/error.
#
# Run via Task Scheduler (setup_watchdog_task.ps1) or manually.
# =============================================================================

$ScriptDir       = "C:\Users\mattm\ThinkorSwim\jarvis-trader"
$LogFile         = "$ScriptDir\watchdog.log"
$LogMaxBytes     = 10MB
$HealthUrl       = "http://localhost:8010/health"
$HealthTimeout   = 10      # seconds per HTTP request
$CheckInterval   = 60      # seconds between health checks
$FailThreshold   = 3       # consecutive failures before restart
$PostRestartWait = 30      # seconds to wait after restart before re-checking

# ── Logging ──────────────────────────────────────────────────────────────────

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $ts   = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] [$Level] $Message"
    Write-Host $line

    # Rotate if log exceeds 10MB
    try {
        if (Test-Path $LogFile) {
            $size = (Get-Item $LogFile).Length
            if ($size -ge $LogMaxBytes) {
                $archive = "$LogFile.1"
                if (Test-Path $archive) { Remove-Item $archive -Force }
                Move-Item $LogFile $archive -Force
                "[$ts] [INFO] Log rotated (previous size: $([math]::Round($size/1MB, 1)) MB)" | Out-File -FilePath $LogFile -Encoding UTF8
            }
        }
    } catch {}

    try {
        $line | Out-File -FilePath $LogFile -Append -Encoding UTF8
    } catch {}
}

# ── WhatsApp Alert ────────────────────────────────────────────────────────────

function Send-WhatsAppAlert {
    param([string]$Msg)
    try {
        # OpenClaw gateway running in WSL on port 3000
        $escaped = $Msg -replace '"', '\"'
        $body    = "{`"message`": `"$escaped`"}"
        $result  = wsl curl -s -X POST http://localhost:3000/api/message `
                      -H "Content-Type: application/json" `
                      -d $body 2>&1
        Write-Log "WhatsApp alert sent (result: $result)" "INFO"
    } catch {
        Write-Log "WhatsApp alert FAILED: $($_.Exception.Message)" "ERROR"
    }
}

# ── Health Check ─────────────────────────────────────────────────────────────

function Test-EngineHealth {
    <#
    .RETURNS
        "ok"        - engine healthy (status == "ok")
        "ibkr_down" - engine up but ibkr_connected=false (not a crash, skip restart)
        "degraded"  - engine up but status != "ok" and not ibkr_only issue
        "down"      - HTTP error / timeout
    #>
    try {
        $resp = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing `
                    -TimeoutSec $HealthTimeout -ErrorAction Stop
        
        $json = $resp.Content | ConvertFrom-Json -ErrorAction SilentlyContinue

        if ($null -eq $json) {
            Write-Log "Health endpoint returned non-JSON (status $($resp.StatusCode))" "WARN"
            return "degraded"
        }

        $status       = $json.status
        $ibkrConn     = $json.ibkr_connected

        if ($status -eq "ok") {
            return "ok"
        }

        # Engine is up and responding, but status != "ok"
        # Check if the ONLY issue is ibkr_connected=false
        # If so, treat as non-crash (IB Gateway may be offline intentionally)
        if ($status -eq "degraded" -and $ibkrConn -eq $false) {
            # Further check: is the DB still connected?
            $dbStatus = $json.database
            if ($dbStatus -eq "connected") {
                # Engine is fine, just IBKR offline — do NOT restart
                return "ibkr_down"
            }
        }

        # Status is something else (degraded with DB error, error, etc.)
        Write-Log "Health returned status='$status' ibkr_connected='$ibkrConn'" "WARN"
        return "degraded"

    } catch [System.Net.WebException] {
        $ex = $_.Exception.Message
        Write-Log "Health check HTTP error: $ex" "WARN"
        return "down"
    } catch {
        Write-Log "Health check error: $($_.Exception.Message)" "WARN"
        return "down"
    }
}

# ── Engine Restart ────────────────────────────────────────────────────────────

function Invoke-EngineRestart {
    Write-Log "Invoking restart_engine.ps1..." "WARN"
    try {
        $proc = Start-Process -FilePath "powershell.exe" `
            -ArgumentList "-ExecutionPolicy Bypass -File `"$ScriptDir\restart_engine.ps1`"" `
            -WorkingDirectory $ScriptDir `
            -PassThru `
            -Wait `
            -WindowStyle Hidden

        if ($proc.ExitCode -ne 0) {
            Write-Log "restart_engine.ps1 exited with code $($proc.ExitCode)" "ERROR"
            return $false
        }
        Write-Log "restart_engine.ps1 completed (exit 0)" "INFO"
        return $true
    } catch {
        Write-Log "Failed to launch restart_engine.ps1: $($_.Exception.Message)" "ERROR"
        return $false
    }
}

# ── Main Loop ────────────────────────────────────────────────────────────────

Write-Log "========================================================" "INFO"
Write-Log "JARVIS Engine Watchdog STARTING" "INFO"
Write-Log "Health URL     : $HealthUrl" "INFO"
Write-Log "Check interval : ${CheckInterval}s" "INFO"
Write-Log "Fail threshold : $FailThreshold consecutive failures" "INFO"
Write-Log "Log file       : $LogFile" "INFO"
Write-Log "========================================================" "INFO"

$consecutiveFails  = 0
$lastHealthStatus  = ""
$watchdogStartTime = Get-Date

while ($true) {
    $healthResult = Test-EngineHealth

    switch ($healthResult) {
        "ok" {
            if ($consecutiveFails -gt 0) {
                Write-Log "Engine recovered after $consecutiveFails failed check(s)" "INFO"
            } else {
                $uptime = [math]::Round(((Get-Date) - $watchdogStartTime).TotalHours, 1)
                Write-Log "Engine healthy (watchdog uptime: ${uptime}h)" "INFO"
            }
            $consecutiveFails = 0
        }

        "ibkr_down" {
            # IB Gateway offline — engine itself is fine, do NOT restart
            if ($lastHealthStatus -ne "ibkr_down") {
                Write-Log "IB Gateway offline (ibkr_connected=false) — engine OK, no restart" "WARN"
            }
            $consecutiveFails = 0    # Reset — this is not an engine crash
        }

        "degraded" {
            $consecutiveFails++
            Write-Log "Engine DEGRADED ($consecutiveFails/$FailThreshold)" "WARN"

            if ($consecutiveFails -ge $FailThreshold) {
                Write-Log "THRESHOLD REACHED — initiating engine restart" "ERROR"
                $restarted = Invoke-EngineRestart

                if ($restarted) {
                    Write-Log "Waiting ${PostRestartWait}s for engine to come up..." "INFO"
                    Start-Sleep -Seconds $PostRestartWait

                    $verifyResult = Test-EngineHealth
                    if ($verifyResult -eq "ok" -or $verifyResult -eq "ibkr_down") {
                        Write-Log "Engine recovered successfully after restart" "INFO"
                        $consecutiveFails = 0
                    } else {
                        Write-Log "Engine still unhealthy after restart (health=$verifyResult)" "ERROR"
                        $alertMsg = "JARVIS ALERT $(Get-Date -Format 'h:mmtt') | ENGINE DEGRADED | Auto-restart failed | Manual intervention needed | Status: $verifyResult"
                        Send-WhatsAppAlert -Msg $alertMsg
                        # Reset counter to avoid restart storm; watchdog continues monitoring
                        $consecutiveFails = 0
                        Start-Sleep -Seconds ($CheckInterval * 3)
                    }
                } else {
                    Write-Log "Restart script failed to execute" "ERROR"
                    $alertMsg = "JARVIS ALERT $(Get-Date -Format 'h:mmtt') | ENGINE DOWN | restart_engine.ps1 failed to run | Manual intervention needed"
                    Send-WhatsAppAlert -Msg $alertMsg
                    $consecutiveFails = 0
                    Start-Sleep -Seconds ($CheckInterval * 3)
                }
            }
        }

        "down" {
            $consecutiveFails++
            Write-Log "Engine DOWN / unreachable ($consecutiveFails/$FailThreshold)" "ERROR"

            if ($consecutiveFails -ge $FailThreshold) {
                Write-Log "THRESHOLD REACHED — initiating engine restart" "ERROR"
                $restarted = Invoke-EngineRestart

                if ($restarted) {
                    Write-Log "Waiting ${PostRestartWait}s for engine to come up..." "INFO"
                    Start-Sleep -Seconds $PostRestartWait

                    $verifyResult = Test-EngineHealth
                    if ($verifyResult -eq "ok" -or $verifyResult -eq "ibkr_down") {
                        Write-Log "Engine is back UP after restart" "INFO"
                        $alertMsg = "JARVIS INFO $(Get-Date -Format 'h:mmtt') | ENGINE RECOVERED | Auto-restart successful"
                        Send-WhatsAppAlert -Msg $alertMsg
                        $consecutiveFails = 0
                    } else {
                        Write-Log "Engine still DOWN after restart (health=$verifyResult)" "ERROR"
                        $alertMsg = "JARVIS ALERT $(Get-Date -Format 'h:mmtt') | ENGINE DOWN | Auto-restart failed | Manual intervention needed"
                        Send-WhatsAppAlert -Msg $alertMsg
                        # Reset counter; keep monitoring but back off to avoid restart storm
                        $consecutiveFails = 0
                        Start-Sleep -Seconds ($CheckInterval * 3)
                    }
                } else {
                    Write-Log "Restart script failed to execute" "ERROR"
                    $alertMsg = "JARVIS ALERT $(Get-Date -Format 'h:mmtt') | ENGINE DOWN | restart_engine.ps1 failed to run | Manual intervention needed"
                    Send-WhatsAppAlert -Msg $alertMsg
                    $consecutiveFails = 0
                    Start-Sleep -Seconds ($CheckInterval * 3)
                }
            }
        }
    }

    $lastHealthStatus = $healthResult
    Start-Sleep -Seconds $CheckInterval
}
