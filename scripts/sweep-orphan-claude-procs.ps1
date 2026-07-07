# sweep-orphan-claude-procs.ps1
# Kills orphan shell/scan processes (powershell, pwsh, bash, find, rg, ripgrep)
# whose immediate parent is dead. Targets the failure pattern where a Claude
# Code session is killed uncleanly and leaves background scans running for hours.
#
# A process is an orphan when:
#   1. Its name matches -TargetNames
#   2. It is older than -MinAgeMinutes (default 30)
#   3. Its ParentProcessId is no longer alive
#      OR its parent's CreationDate is AFTER the child's (PID was recycled)
#
# Defaults to dry-run. Pass -Apply to actually kill.
#
# Usage:
#   .\sweep-orphan-claude-procs.ps1                   # dry-run
#   .\sweep-orphan-claude-procs.ps1 -Apply            # execute
#   .\sweep-orphan-claude-procs.ps1 -MinAgeMinutes 60 # only kill >1h old
#
# Designed to run via Jarvis-OrphanProcSweep scheduled task hourly.
# Log: ~/scripts/.sweep-orphan-claude-procs.log

[CmdletBinding()]
param(
    [switch]$Apply,
    [int]$MinAgeMinutes = 30,
    [string[]]$TargetNames = @('powershell.exe', 'pwsh.exe', 'bash.exe', 'find.exe', 'rg.exe', 'ripgrep.exe')
)

$ErrorActionPreference = 'Continue'
$logPath = Join-Path $HOME 'scripts\.sweep-orphan-claude-procs.log'
$now = Get-Date
$cutoff = $now.AddMinutes(-$MinAgeMinutes)
$selfPid = $PID

# Single CIM call; build PID->process hashtable for O(1) parent lookup.
# CIM avoids the access-denied issues that Get-Process hits on cross-user processes.
$allProcs = @{}
foreach ($p in Get-CimInstance Win32_Process) {
    $allProcs[[string]$p.ProcessId] = $p
}

$candidates = $allProcs.Values | Where-Object { $TargetNames -contains $_.Name }

$victims = New-Object System.Collections.Generic.List[psobject]
foreach ($c in $candidates) {
    if ($c.ProcessId -eq $selfPid) { continue }
    if ($null -eq $c.CreationDate -or $c.CreationDate -gt $cutoff) { continue }

    $parent = $allProcs[[string]$c.ParentProcessId]
    $reason = $null
    if (-not $parent) {
        $reason = "parent PID $($c.ParentProcessId) dead"
    }
    elseif ($parent.CreationDate -and $parent.CreationDate -gt $c.CreationDate) {
        $reason = "PID-recycle (parent $($parent.Name)/$($parent.ProcessId) started $($parent.CreationDate.ToString('s')))"
    }
    if (-not $reason) { continue }

    $cmd = if ($c.CommandLine) {
        $cl = $c.CommandLine
        if ($cl.Length -gt 140) { $cl.Substring(0, 140) + '...' } else { $cl }
    }
    else { '' }

    $victims.Add([PSCustomObject]@{
            PID     = $c.ProcessId
            Name    = $c.Name
            PPID    = $c.ParentProcessId
            AgeHrs  = [math]::Round(($now - $c.CreationDate).TotalHours, 1)
            MemMB   = [math]::Round($c.WorkingSetSize / 1MB, 1)
            Reason  = $reason
            CmdLine = $cmd
        })
}

$header = "[$($now.ToString('yyyy-MM-dd HH:mm:ss'))] sweep-orphan-claude-procs Apply=$Apply MinAge=${MinAgeMinutes}min  candidates=$(@($candidates).Count) victims=$($victims.Count)"
$logLines = New-Object System.Collections.Generic.List[string]
[void]$logLines.Add($header)
foreach ($v in $victims) {
    [void]$logLines.Add(("  PID={0,6} {1,-15} PPID={2,6} Age={3}h Mem={4}MB  {5}  Cmd={6}" -f $v.PID, $v.Name, $v.PPID, $v.AgeHrs, $v.MemMB, $v.Reason, $v.CmdLine))
}

$failed = 0
if ($victims.Count -eq 0) {
    [void]$logLines.Add("  (no orphans)")
    Write-Output "No orphans found (scanned $(@($candidates).Count) candidates older than $MinAgeMinutes min)."
}
elseif ($Apply) {
    $killed = 0
    foreach ($v in $victims) {
        try {
            Stop-Process -Id $v.PID -Force -ErrorAction Stop
            $killed++
        }
        catch {
            $failed++
            [void]$logLines.Add("    KILL FAILED PID=$($v.PID): $($_.Exception.Message)")
        }
    }
    [void]$logLines.Add("  killed=$killed failed=$failed")
    Write-Output "Killed $killed orphan(s), $failed failed."
}
else {
    Write-Output "DRY-RUN -- would kill $($victims.Count) orphan(s):"
    $victims | Format-Table PID, Name, PPID, AgeHrs, MemMB, Reason -AutoSize
    Write-Output "Run with -Apply to terminate. Log: $logPath"
}

Add-Content -Path $logPath -Value (($logLines -join "`n") + "`n")
if ($failed -gt 0) { exit 1 } else { exit 0 }
