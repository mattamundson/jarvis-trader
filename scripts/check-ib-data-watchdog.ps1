#Requires -Version 5.1
<#
.SYNOPSIS
  Overseer liveness check for the IB data-leg auto-reconnect watchdog (US-010).

.DESCRIPTION
  Consumes the engine's /health/full endpoint and inspects
  subsystems.ib_gateway.watchdog (shipped in PR #68, see ib_data_watchdog.py).
  Returns a scheduled-check exit-code contract so the master overseer
  (Jarvis-MasterOverseer) can escalate a sustained data-down condition on the
  unified pane.

  /health/full is auth-exempt (middleware/auth.py EXEMPT_PATHS) -- no API key
  required.

  EXIT-CODE CONTRACT
    0  OK         -- watchdog present and healthy (consecutive_failures below
                     threshold), OR watchdog absent but outside market hours
                     (not actionable -- e.g. engine predates the feature).
    1  ALERT      -- one of:
                       * watchdog.consecutive_failures >= FailureThreshold
                         (sustained reconnect failure)
                       * watchdog missing/absent DURING market hours
                       * watchdog enabled but not running DURING market hours
                     Failures occurring inside the configured IB Gateway daily
                     restart window are suppressed (expected churn).
    2  UNREACHABLE -- engine did not answer /health/full (down or wrong port).

  The "during market hours" gate (coarse: weekday + RTH in US/Eastern) prevents
  false alarms overnight/weekends when an absent watchdog is not actionable.

.PARAMETER EngineUrl
  Full /health/full URL. Default http://127.0.0.1:8010/health/full
  (127.0.0.1 literal, never localhost -- Windows IPv6 quirk).

.PARAMETER FailureThreshold
  consecutive_failures >= this => ALERT. Default 3.

.PARAMETER MarketOpen
  US/Eastern RTH open HH:MM for the coarse market-hours gate. Default 09:30.

.PARAMETER MarketClose
  US/Eastern RTH close HH:MM for the coarse market-hours gate. Default 16:00.

.PARAMETER TimeoutSec
  HTTP timeout in seconds. Default 8.

.PARAMETER FromFile
  Read the /health/full JSON body from a file instead of HTTP. For testing /
  dry-run verification of the decision logic against fixtures.

.PARAMETER Json
  Emit a single machine-readable JSON object instead of a human line.

.EXAMPLE
  pwsh -NoProfile -File scripts\check-ib-data-watchdog.ps1
  Probe the live engine; exit 0/1/2 for a scheduled overseer check.

.EXAMPLE
  pwsh -NoProfile -File scripts\check-ib-data-watchdog.ps1 -Json
  Same, but print a JSON verdict (status, reason, consecutive_failures, ...).

.NOTES
  Wire into the overseer by adding to a scheduled sweep, e.g.:
    schtasks /Create /SC MINUTE /MO 5 /TN "Jarvis-IBDataWatchdogCheck" ^
      /TR "pwsh -NoProfile -File <repo>\scripts\check-ib-data-watchdog.ps1" /RL LIMITED
  Exit 1 (ALERT) / 2 (UNREACHABLE) surfaces as LastTaskResult for the overseer
  to escalate. Run via the WindowsApps pwsh shim, not a versioned path.
#>
[CmdletBinding()]
param(
    [string]$EngineUrl       = 'http://127.0.0.1:8010/health/full',
    [int]   $FailureThreshold = 3,
    [string]$MarketOpen       = '09:30',
    [string]$MarketClose      = '16:00',
    [int]   $TimeoutSec       = 8,
    [string]$FromFile,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'

# Exit-code contract
$EXIT_OK          = 0
$EXIT_ALERT       = 1
$EXIT_UNREACHABLE = 2

function Test-MarketHours {
    # Coarse weekday + RTH gate in US/Eastern (DST-aware via the Windows tz id).
    try {
        $tz    = [System.TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
        $nowEt = [System.TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $tz)
    } catch {
        # If tz lookup fails, fall back to local time -- better to over-alert
        # than to silently swallow a real data-down during the day.
        $nowEt = Get-Date
    }
    if ($nowEt.DayOfWeek -eq 'Saturday' -or $nowEt.DayOfWeek -eq 'Sunday') {
        return $false
    }
    $open  = [TimeSpan]::Parse($MarketOpen)
    $close = [TimeSpan]::Parse($MarketClose)
    $t     = $nowEt.TimeOfDay
    return ($t -ge $open -and $t -lt $close)
}

function Write-Verdict([string]$status, [string]$reason, $wd, [int]$code, [bool]$inMkt) {
    $cf = $null; $lr = $null; $en = $null; $run = $null; $inRw = $null
    if ($wd) {
        $cf   = $wd.consecutive_failures
        $lr   = $wd.last_reconnect_ts
        $en   = $wd.enabled
        $run  = $wd.running
        $inRw = $wd.in_restart_window
    }
    if ($Json) {
        $obj = [ordered]@{
            status               = $status
            reason               = $reason
            exit_code            = $code
            watchdog_present     = [bool]$wd
            enabled              = $en
            running              = $run
            consecutive_failures = $cf
            failure_threshold    = $FailureThreshold
            last_reconnect_ts    = $lr
            in_restart_window    = $inRw
            in_market_hours      = $inMkt
            checked_at           = (Get-Date).ToString('o')
        }
        $obj | ConvertTo-Json -Compress
    } else {
        $cfTxt = if ($null -ne $cf) { $cf } else { 'n/a' }
        Write-Host ("[{0}] {1} -- {2} (consecutive_failures={3}, market_hours={4})" -f `
            $status, (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $reason, $cfTxt, $inMkt)
    }
}

# --- Fetch /health/full -------------------------------------------------------
$body = $null
if ($FromFile) {
    if (-not (Test-Path $FromFile)) {
        Write-Verdict 'UNREACHABLE' "fixture not found: $FromFile" $null $EXIT_UNREACHABLE $false
        exit $EXIT_UNREACHABLE
    }
    $body = Get-Content -Path $FromFile -Raw | ConvertFrom-Json
} else {
    try {
        $body = Invoke-RestMethod -Uri $EngineUrl -TimeoutSec $TimeoutSec -UseBasicParsing
    } catch {
        Write-Verdict 'UNREACHABLE' "engine did not answer $EngineUrl ($($_.Exception.Message))" `
            $null $EXIT_UNREACHABLE $false
        exit $EXIT_UNREACHABLE
    }
}

$inMkt = Test-MarketHours

# Navigate defensively: subsystems.ib_gateway.watchdog (null on older engines).
$wd = $null
try { $wd = $body.subsystems.ib_gateway.watchdog } catch { $wd = $null }

# --- Decision tree ------------------------------------------------------------
if (-not $wd) {
    if ($inMkt) {
        Write-Verdict 'ALERT' 'watchdog absent during market hours (engine predates the watchdog, or it failed to start)' `
            $null $EXIT_ALERT $inMkt
        exit $EXIT_ALERT
    }
    Write-Verdict 'OK' 'watchdog absent but outside market hours -- not actionable' `
        $null $EXIT_OK $inMkt
    exit $EXIT_OK
}

# Watchdog present.
$failures = 0
if ($null -ne $wd.consecutive_failures) { $failures = [int]$wd.consecutive_failures }
$inRestart = [bool]$wd.in_restart_window
$enabled   = if ($null -eq $wd.enabled) { $true } else { [bool]$wd.enabled }
$running   = if ($null -eq $wd.running) { $true } else { [bool]$wd.running }

if ($inRestart) {
    Write-Verdict 'OK' "in IB Gateway restart window -- failure alerts suppressed (consecutive_failures=$failures)" `
        $wd $EXIT_OK $inMkt
    exit $EXIT_OK
}

if ($failures -ge $FailureThreshold) {
    Write-Verdict 'ALERT' "sustained reconnect failure: consecutive_failures=$failures >= $FailureThreshold" `
        $wd $EXIT_ALERT $inMkt
    exit $EXIT_ALERT
}

if ($enabled -and -not $running -and $inMkt) {
    Write-Verdict 'ALERT' 'watchdog enabled but not running during market hours' `
        $wd $EXIT_ALERT $inMkt
    exit $EXIT_ALERT
}

Write-Verdict 'OK' "watchdog healthy (enabled=$enabled, running=$running, consecutive_failures=$failures)" `
    $wd $EXIT_OK $inMkt
exit $EXIT_OK
