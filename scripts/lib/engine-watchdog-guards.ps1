#Requires -Version 5.1
<#
.SYNOPSIS
  Pure, side-effect-free decision helpers for engine-watchdog.ps1.

.DESCRIPTION
  Extracted so the restart-storm guard (2026-06-18) is unit-testable in
  isolation. This file defines functions ONLY -- it performs no health probes,
  no kills, and no restarts -- so it is safe to dot-source from a Pester test.
  ASCII-only (PS 5.1 parses .ps1 as the ANSI code page; non-ASCII breaks it).
#>

function Test-EngineLogFresh {
    <#
    .SYNOPSIS
      Decide whether the engine log is "fresh" enough to prove the event loop
      is still alive, so a slow /health is saturation rather than death.

    .DESCRIPTION
      Mirrors the 2026-06-18 log-recency guard. A log line written within
      ThresholdSec means apscheduler jobs / IBKR bars / TVStreamer reads are
      still flowing -- the loop is alive -> SKIP the restart. A stale log (or a
      log that cannot be stat'd at all) is treated as NOT fresh, so the caller
      falls through to the kill+restart (fail-safe, preserves prior behavior).

    .PARAMETER LogPath
      Path to the engine error log (pm2 jarvis-engine-error.log).

    .PARAMETER ThresholdSec
      Freshness window in seconds. Age strictly < ThresholdSec is "fresh".

    .PARAMETER Now
      Reference time (injectable for testing). Defaults to the current time.

    .OUTPUTS
      [pscustomobject] with:
        Statted [bool]  - whether the log file could be stat'd
        Fresh   [bool]  - age < ThresholdSec (always $false when not statted)
        AgeSec  [double]- age in seconds (NaN when not statted)
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$LogPath,
        [double]$ThresholdSec = 60,
        [datetime]$Now = (Get-Date)
    )

    try {
        $item   = Get-Item -LiteralPath $LogPath -ErrorAction Stop
        $ageSec = ($Now - $item.LastWriteTime).TotalSeconds
        return [pscustomobject]@{
            Statted = $true
            Fresh   = ($ageSec -lt $ThresholdSec)
            AgeSec  = $ageSec
        }
    } catch {
        # Cannot stat the log (missing / locked) -> fail-safe to NOT fresh so the
        # watchdog falls through to restart, exactly as the original inline guard.
        return [pscustomobject]@{
            Statted = $false
            Fresh   = $false
            AgeSec  = [double]::NaN
        }
    }
}
