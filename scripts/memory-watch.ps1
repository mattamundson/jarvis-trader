# memory-watch.ps1
# Continuous memory-pressure watcher. Detects:
#   - Low Available RAM
#   - Sustained pagefile thrashing (high Page Reads/sec)
#   - Approaching commit-limit exhaustion
#
# Logs to ~/scripts/.memory-watch.log on every run.
# Tracks state in ~/scripts/.memory-watch-state.json so the same condition
# doesn't spam Telegram every 15 min — only on state transitions or after
# AlertCooldownHours has elapsed.
#
# Designed to run via Jarvis-MemoryWatch scheduled task every 15 minutes.
# Wrapped via notify-on-fail.ps1 — non-zero exit = Telegram alert.
#
# Usage:
#   .\memory-watch.ps1                    # log + console summary
#   .\memory-watch.ps1 -Quiet             # log only (use in scheduled task)
#   .\memory-watch.ps1 -Quiet -Notify     # log + non-zero exit on first ALERT

[CmdletBinding()]
param(
    [int]$WarnAvailableGB = 3,
    [int]$AlertAvailableGB = 1,
    [int]$WarnPageReadsRate = 500,
    [int]$AlertPageReadsRate = 1000,
    [int]$WarnCommitPct = 85,
    [int]$AlertCommitPct = 95,
    [int]$AlertCooldownHours = 2,
    [switch]$Quiet,
    [switch]$Notify
)

$ErrorActionPreference = 'Continue'
$logPath = Join-Path $HOME 'scripts\.memory-watch.log'
$statePath = Join-Path $HOME 'scripts\.memory-watch-state.json'
$now = Get-Date

# Sample current pressure
$availMB = (Get-Counter '\Memory\Available MBytes' -SampleInterval 1 -MaxSamples 1).CounterSamples[0].CookedValue
$availGB = [math]::Round($availMB / 1024, 1)
$pageReads = [math]::Round((Get-Counter '\Memory\Page Reads/sec' -SampleInterval 2 -MaxSamples 1).CounterSamples[0].CookedValue, 0)
$commitGB = [math]::Round((Get-Counter '\Memory\Committed Bytes').CounterSamples[0].CookedValue / 1GB, 1)
$commitLimGB = [math]::Round((Get-Counter '\Memory\Commit Limit').CounterSamples[0].CookedValue / 1GB, 1)
$commitPct = [math]::Round(($commitGB / $commitLimGB) * 100, 0)
$cpuPct = [math]::Round((Get-Counter '\Processor(_Total)\% Processor Time' -SampleInterval 1 -MaxSamples 1).CounterSamples[0].CookedValue, 0)

# Determine severity
$severity = 'OK'
$reasons = New-Object System.Collections.Generic.List[string]

function Set-Worse([string]$candidate) {
    $rank = @{ 'OK' = 0; 'WARN' = 1; 'ALERT' = 2 }
    if ($rank[$candidate] -gt $rank[$script:severity]) { $script:severity = $candidate }
}

if ($availGB -le $AlertAvailableGB) { Set-Worse 'ALERT'; $reasons.Add("AvailRAM=${availGB}GB <= ${AlertAvailableGB}GB") }
elseif ($availGB -le $WarnAvailableGB) { Set-Worse 'WARN'; $reasons.Add("AvailRAM=${availGB}GB <= ${WarnAvailableGB}GB") }

if ($pageReads -ge $AlertPageReadsRate) { Set-Worse 'ALERT'; $reasons.Add("PageReads/s=${pageReads} >= ${AlertPageReadsRate}") }
elseif ($pageReads -ge $WarnPageReadsRate) { Set-Worse 'WARN'; $reasons.Add("PageReads/s=${pageReads} >= ${WarnPageReadsRate}") }

if ($commitPct -ge $AlertCommitPct) { Set-Worse 'ALERT'; $reasons.Add("Commit=${commitPct}% >= ${AlertCommitPct}%") }
elseif ($commitPct -ge $WarnCommitPct) { Set-Worse 'WARN'; $reasons.Add("Commit=${commitPct}% >= ${WarnCommitPct}%") }

# Top consumers (only when not OK — keeps log light)
$topLines = @()
if ($severity -ne 'OK') {
    $top = Get-Process -ErrorAction SilentlyContinue | Group-Object Name | ForEach-Object {
        [PSCustomObject]@{
            Name    = $_.Name
            Count   = $_.Count
            TotalMB = [math]::Round(($_.Group | Measure-Object WS -Sum).Sum / 1MB, 0)
        }
    } | Where-Object { $_.TotalMB -ge 100 } | Sort-Object TotalMB -Descending | Select-Object -First 10
    $topLines = $top | ForEach-Object { '    {0,-25} count={1,3}  totalMB={2,5:N0}' -f $_.Name, $_.Count, $_.TotalMB }
}

# State tracking — only alert on transitions or after cooldown
$state = if (Test-Path $statePath) {
    try { Get-Content $statePath -Raw | ConvertFrom-Json } catch { $null }
}
else { $null }
if ($null -eq $state) {
    $state = [PSCustomObject]@{ lastSeverity = 'OK'; lastAlerted = $null }
}

$shouldAlert = $false
if ($severity -eq 'ALERT') {
    if ($state.lastSeverity -ne 'ALERT') {
        $shouldAlert = $true
    }
    elseif ($state.lastAlerted) {
        $hoursSince = ($now - [datetime]$state.lastAlerted).TotalHours
        if ($hoursSince -ge $AlertCooldownHours) { $shouldAlert = $true }
    }
}

if ($shouldAlert) {
    $state.lastAlerted = $now.ToString('o')
}
$state.lastSeverity = $severity
$state | ConvertTo-Json -Compress | Set-Content -Path $statePath

# Compose log entry
$header = '[{0}] mem-watch [{1}] avail={2}GB pageReads/s={3} commit={4}/{5}GB ({6}%) cpu={7}%' -f `
    $now.ToString('yyyy-MM-dd HH:mm:ss'), $severity, $availGB, $pageReads, $commitGB, $commitLimGB, $commitPct, $cpuPct

$logLines = New-Object System.Collections.Generic.List[string]
[void]$logLines.Add($header)
if ($reasons.Count -gt 0) { [void]$logLines.Add('  reasons: ' + ($reasons -join '; ')) }
foreach ($l in $topLines) { [void]$logLines.Add($l) }
if ($shouldAlert) { [void]$logLines.Add('  >>> ALERT FIRED (state transition or cooldown elapsed) <<<') }

Add-Content -Path $logPath -Value (($logLines -join "`n") + "`n")

if (-not $Quiet) {
    foreach ($l in $logLines) { Write-Output $l }
}

# Trigger notify-on-fail.ps1 → Telegram only on first ALERT or after cooldown
if ($Notify -and $shouldAlert) { exit 1 }
exit 0
