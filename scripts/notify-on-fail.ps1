# notify-on-fail.ps1 -- run a regression worker, alert on non-zero exit
#
# Wraps the actual worker so Windows Task Scheduler captures a single exit code
# while still getting visibility into failures via local log + optional Telegram.
#
# Usage:
#   notify-on-fail.ps1 -WorkerName scan-credentials
#   notify-on-fail.ps1 -WorkerName archive-rotate -ExtraArgs "-Execute"
#
# Telegram is sent ONLY when EITHER:
#   - 1Password CLI ('op') is configured AND
#     op://Amo Personal/Telegram-Hermes-Bot/{token,chat_id} resolves
#   - $env:TELEGRAM_BOT_TOKEN + $env:TELEGRAM_CHAT_ID are set
# Otherwise: failures are logged to ~/scripts/.regression-alerts.log only.
#
# Exit code is always the worker's exit code (so Task Scheduler last-result is
# meaningful).

[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$WorkerName,
    [string]$ExtraArgs = ""
)

$ErrorActionPreference = "Continue"

$ScriptsDir = $PSScriptRoot
$WorkerPath = Join-Path $ScriptsDir "$WorkerName.ps1"
$LogFile = Join-Path $ScriptsDir ".regression-alerts.log"

if (-not (Test-Path $WorkerPath)) {
    "[$(Get-Date -Format 'o')] notify-on-fail: worker not found: $WorkerPath" |
        Add-Content -LiteralPath $LogFile -Encoding UTF8
    exit 127
}

$startTime = Get-Date

# Build worker invocation
$argv = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $WorkerPath)
if ($ExtraArgs) {
    # Naive whitespace split is fine for our worker args (-Execute, -Top 15, etc.)
    $argv += ($ExtraArgs -split '\s+' | Where-Object { $_ })
}

# Run worker; merge stderr into stdout via 2>&1 so we capture everything in one
# stream. Call operator preserves $LASTEXITCODE from the child powershell.
$output = ""
$exitCode = 1
try {
    $output = (& powershell.exe @argv 2>&1 | Out-String)
    $exitCode = $LASTEXITCODE
    # If the child process didn't set an exit code (e.g. exit 0 path), default to 0
    if ($null -eq $exitCode) { $exitCode = 0 }
}
catch {
    "[$(Get-Date -Format 'o')] notify-on-fail: launch error for ${WorkerName}: $_" |
        Add-Content -LiteralPath $LogFile -Encoding UTF8
}

# Replay worker output so the Task Scheduler last-run shows it
if ($output) { Write-Host $output }

if ($exitCode -ne 0) {
    $duration = [Math]::Round(((Get-Date) - $startTime).TotalSeconds, 1)
    $tail = ($output -split "`n" | Select-Object -Last 50) -join "`n"

    $entry = "[$(Get-Date -Format 'o')] $WorkerName exit=$exitCode duration=${duration}s`n$tail`n---`n"
    Add-Content -LiteralPath $LogFile -Value $entry -Encoding UTF8

    $sent = $false

    # Try 1Password first
    $token = $null
    $chatId = $null
    try {
        $opTok = & op read "op://Amo Personal/Telegram-Hermes-Bot/token" 2>$null
        if ($LASTEXITCODE -eq 0 -and $opTok) { $token = $opTok }
        $opChat = & op read "op://Amo Personal/Telegram-Hermes-Bot/chat_id" 2>$null
        if ($LASTEXITCODE -eq 0 -and $opChat) { $chatId = $opChat }
    }
    catch {}

    # Fallback to env vars
    if (-not $token) { $token = $env:TELEGRAM_BOT_TOKEN }
    if (-not $chatId) { $chatId = $env:TELEGRAM_CHAT_ID }

    if ($token -and $chatId) {
        try {
            $msg = "[JARVIS] regression FAIL: $WorkerName (exit=$exitCode, ${duration}s)`n$tail"
            if ($msg.Length -gt 4000) { $msg = $msg.Substring(0, 4000) + "...[truncated]" }
            $resp = Invoke-RestMethod `
                -Method POST `
                -Uri "https://api.telegram.org/bot$token/sendMessage" `
                -Body @{ chat_id = $chatId; text = $msg } `
                -TimeoutSec 10
            if ($resp.ok) {
                $sent = $true
                Add-Content -LiteralPath $LogFile -Value "  -> telegram sent" -Encoding UTF8
            }
        }
        catch {
            Add-Content -LiteralPath $LogFile -Value "  -> telegram error: $_" -Encoding UTF8
        }
    }

    if (-not $sent) {
        Add-Content -LiteralPath $LogFile -Value "  -> telegram skipped (no creds via op or env)" -Encoding UTF8
    }
}

exit $exitCode
