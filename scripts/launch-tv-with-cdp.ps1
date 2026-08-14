# launch-tv-with-cdp.ps1 — Launch TradingView Desktop with Chrome DevTools Protocol enabled.
#
# Purpose: The TradingView MCP server (tradingview-mcp/) requires TV Desktop to be
# running with --remote-debugging-port=9222 so the MCP server can connect via CDP.
# TV Desktop launched from the Start menu does NOT set this flag by default,
# which leaves the MCP dormant.
#
# States handled:
#   CDP-UP                     → nothing to do (exit 0)
#   CDP-DOWN + TV-STOPPED      → launch TV with CDP flag (exit 0 / 1)
#   CDP-DOWN + TV-RUNNING      → without -AutoHeal: warn + exit 2 (preserve user session)
#                                with -AutoHeal inside safe window: kill + relaunch
#                                with -AutoHeal outside safe window: warn + exit 2
#
# Safe-window for auto-kill (futures 24/5; assume user may be watching charts):
#   - Weekdays 18:00-07:00 CT (overnight, post-close to pre-market)
#   - All day Sat/Sun
#   - Any time if $env:JARVIS_FORCE_TV_RELAUNCH = "1" (manual override)
#
# Idempotent. Safe to run on login, manually, or from another scheduled watchdog task.
#
# Logs to: $env:USERPROFILE\jarvis-tv-cdp.log (rotated when >1MB)
#
# Exit codes:
#   0 = CDP alive (already was, or was just launched / auto-healed)
#   1 = hard failure (binary missing, launch failed)
#   2 = soft config gap (TV running without CDP and auto-heal skipped)
#
# Usage:
#   pwsh -NoProfile -File scripts\launch-tv-with-cdp.ps1                    # detect-only
#   pwsh -NoProfile -File scripts\launch-tv-with-cdp.ps1 -AutoHeal          # detect + kill+relaunch in safe windows
#
# Triggers:
#   - JARVIS-TV-CDP-AtLogon    (AtLogon, no -AutoHeal)       --> covers login case
#   - JARVIS-TV-CDP-Watchdog   (every 10min, -AutoHeal)      --> covers auto-update / wake-from-sleep

param(
    [switch]$AutoHeal
)

$ErrorActionPreference = "Stop"

# ── Config ─────────────────────────────────────────────────────────────────────
$cdpPort       = 9222
# Discover the installed TV Desktop version dir via wildcard resolve — survives
# Microsoft Store auto-updates that rotate the version-stamped folder name (e.g.
# 3.0.0.7652 → 3.0.0.7800). Resolve-Path with wildcards works from user context
# without admin rights; Get-ChildItem on WindowsApps usually does not. Fallback
# to the last-known path keeps old behaviour if discovery silently returns null.
$tvResolved    = Resolve-Path "C:\Program Files\WindowsApps\TradingView.Desktop_*_x64__*\TradingView.exe" -ErrorAction SilentlyContinue | Select-Object -Last 1
$tvBinary      = if ($tvResolved) { $tvResolved.Path } else { "C:\Program Files\WindowsApps\TradingView.Desktop_3.0.0.7652_x64__n534cwy3pjxzj\TradingView.exe" }
$logPath       = Join-Path $env:USERPROFILE "jarvis-tv-cdp.log"
# Chromium 136+ ignores --remote-debugging-port for the default profile.
# Use a dedicated JARVIS profile so CDP remains available without weakening
# the protection on TradingView's normal credential-bearing profile.
$cdpProfileDir = Join-Path $env:LOCALAPPDATA "JARVIS\TradingView-CDP-Profile"
$maxLogBytes   = 1MB
$launchTimeoutSec = 30  # 2026-04-24: bumped from 15s — TV cold-start observed at 22s (23:33) and 26s (failed at 23:23). 15s triggered false-failure on the 2026-04-23 22:23 scheduled-task fire (LastResult=1).

# ── Logging ────────────────────────────────────────────────────────────────────
if ((Test-Path $logPath) -and ((Get-Item $logPath).Length -gt $maxLogBytes)) {
    $backup = "$logPath.1"
    if (Test-Path $backup) { Remove-Item $backup -Force }
    Move-Item $logPath $backup -Force
}

function Write-Log {
    param([string]$msg, [string]$level = "INFO")
    $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $line = "[$ts] [$level] $msg"
    Add-Content -Path $logPath -Value $line -Encoding UTF8
    Write-Host $line
}

Write-Log "launch-tv-with-cdp.ps1 starting"

# ── Step 1: Is CDP already alive? ──────────────────────────────────────────────
function Test-CdpAlive {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$cdpPort/json/version" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        return $resp.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Start-TradingViewMsix {
    param([string]$Arguments)
    if (-not ('JarvisApplicationActivation.TVLauncher' -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
namespace JarvisApplicationActivation {
    public class TVLauncher {
        [ComImport]
        [Guid("2e941141-7f97-4756-ba1d-9decde894a3d")]
        [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        public interface IApplicationActivationManager {
            int ActivateApplication([MarshalAs(UnmanagedType.LPWStr)] string appUserModelId,
                [MarshalAs(UnmanagedType.LPWStr)] string arguments, int options, out uint processId);
        }
        [ComImport]
        [Guid("45ba127d-10a8-46ea-8ab7-56ea9078943c")]
        public class ApplicationActivationManager { }
        public static uint Launch(string appUserModelId, string arguments) {
            var manager = (IApplicationActivationManager)new ApplicationActivationManager();
            uint processId;
            int result = manager.ActivateApplication(appUserModelId, arguments, 0, out processId);
            if (result != 0) { Marshal.ThrowExceptionForHR(result); }
            return processId;
        }
    }
}
"@ -ErrorAction Stop
    }
    $package = Get-AppxPackage -Name 'TradingView.Desktop' -ErrorAction Stop
    $aumid = "$($package.PackageFamilyName)!TradingView.Desktop"
    return [JarvisApplicationActivation.TVLauncher]::Launch($aumid, $Arguments)
}

if (Test-CdpAlive) {
    Write-Log "CDP already alive on port $cdpPort — nothing to do"
    exit 0
}

# ── Step 2: Is TV running without CDP? ────────────────────────────────────────
function Test-IsSafeKillWindow {
    # Safe windows for killing a live TV session: overnight + weekends, or explicit override.
    if ($env:JARVIS_FORCE_TV_RELAUNCH -eq "1") { return $true }
    $now = Get-Date
    $dow = $now.DayOfWeek  # Sunday=0..Saturday=6
    if ($dow -eq 'Saturday' -or $dow -eq 'Sunday') { return $true }
    $h = $now.Hour  # local time on this box (America/Chicago when CT)
    # 18:00-23:59 CT OR 00:00-06:59 CT = overnight off-market futures window
    if ($h -ge 18 -or $h -lt 7) { return $true }
    return $false
}

$tvProcs = @(Get-Process TradingView -ErrorAction SilentlyContinue)
if ($tvProcs.Count -gt 0) {
    if ($AutoHeal -and (Test-IsSafeKillWindow)) {
        Write-Log "TV running without CDP; -AutoHeal set and inside safe-kill window. Terminating $($tvProcs.Count) TV processes and relaunching with --remote-debugging-port=$cdpPort." "WARN"
        $tvProcs | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        # Escape hatch for stuck children
        $remaining = @(Get-Process TradingView -ErrorAction SilentlyContinue)
        if ($remaining.Count -gt 0) {
            & taskkill /F /IM TradingView.exe /T 2>&1 | Out-Null
            Start-Sleep -Seconds 2
        }
        # Fall through to Step 3 (fresh launch)
    } else {
        $reason = if ($AutoHeal) { "-AutoHeal set but outside safe-kill window (weekday 07:00-18:00 CT)" } else { "-AutoHeal not set" }
        Write-Log "TV Desktop is running ($($tvProcs.Count) processes) but CDP port $cdpPort is not responding. $reason. Not killing the session — user may have unsaved layouts. Relaunch manually via: taskkill /IM TradingView.exe /F; then rerun this script. Or set \$env:JARVIS_FORCE_TV_RELAUNCH='1' and rerun with -AutoHeal." "WARN"
        exit 2
    }
}

# ── Step 3: Launch TV with CDP flag ────────────────────────────────────────────
if (-not (Test-Path $tvBinary)) {
    Write-Log "TV binary not found at: $tvBinary. If TV was updated via the Microsoft Store, the version-stamped path may have changed. Find the new path via: Get-Process TradingView | Select Path" "ERROR"
    exit 1
}

Write-Log "Launching TV Desktop with --remote-debugging-port=$cdpPort"
try {
    New-Item -ItemType Directory -Path $cdpProfileDir -Force | Out-Null
    $launchArgs = @(
        "--remote-debugging-port=$cdpPort"
        "--remote-debugging-address=127.0.0.1"
        "--user-data-dir=$cdpProfileDir"
    )
    if ($tvBinary -like '*\WindowsApps\*') {
        $activatedPid = Start-TradingViewMsix -Arguments ($launchArgs -join ' ')
        Write-Log "TradingView MSIX activated through IApplicationActivationManager (pid=$activatedPid)"
    }
    else {
        Start-Process -FilePath $tvBinary -ArgumentList $launchArgs
    }
} catch {
    Write-Log "Start-Process failed: $($_.Exception.Message)" "ERROR"
    exit 1
}

# ── Step 4: Wait for CDP to come up ────────────────────────────────────────────
$deadline = (Get-Date).AddSeconds($launchTimeoutSec)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
    if (Test-CdpAlive) {
        Write-Log "CDP alive on port $cdpPort — launch successful"
        exit 0
    }
}

Write-Log "TV launched but CDP did not bind to port $cdpPort within ${launchTimeoutSec}s. Check the Electron/Chromium version + Store sandbox restrictions." "ERROR"
exit 1
