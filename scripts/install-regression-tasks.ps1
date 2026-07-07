# install-regression-tasks.ps1 -- register Phase 7 regression-prevention tasks
#
# Replaces the (architecturally-wrong) /schedule cloud-routine plan with
# Windows Task Scheduler entries. The cloud routines in claude.ai/code/routines
# can't see C:\Users\mattm\, so filesystem-touching scans must run locally.
#
# Idempotent (uses Register-ScheduledTask -Force).
# Run once with admin: .\install-regression-tasks.ps1
# Uninstall:           .\install-regression-tasks.ps1 -Uninstall
# Dry-run:             .\install-regression-tasks.ps1 -DryRun
#
# After install, verify:
#   Get-ScheduledTask -TaskName 'Jarvis-*' | Format-Table TaskName,State,@{N='NextRun';E={(Get-ScheduledTaskInfo $_).NextRunTime}}
#
# Test a single task immediately:
#   Start-ScheduledTask -TaskName 'Jarvis-ScanCredentials'
#   # then: Get-ScheduledTaskInfo -TaskName 'Jarvis-ScanCredentials' | Select LastRunTime,LastTaskResult

[CmdletBinding()]
param(
    [switch]$Uninstall,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin -and -not $DryRun) {
    Write-Error "Must be run elevated. Right-click PowerShell > 'Run as Administrator'. (Or use -DryRun to preview.)"
    exit 1
}

$ScriptsDir = "C:\Users\mattm\scripts"

# Times below are LOCAL (America/Chicago). Task Scheduler stores them as local
# and applies the OS timezone at fire time -- DST is handled automatically.
$tasks = @(
    @{
        Name        = "Jarvis-ScanCredentials"
        Description = "Weekly credential leak scan -- patterns from secret-hygiene.md"
        Worker      = "scan-credentials.ps1"
        Args        = ""
        TriggerArgs = @{ Weekly = $true; DaysOfWeek = "Sunday"; At = "09:00" }
    },
    @{
        Name        = "Jarvis-ScanUncommitted"
        Description = "Weekday uncommitted-work scan across active git repos"
        Worker      = "scan-uncommitted.ps1"
        Args        = ""
        TriggerArgs = @{ Weekly = $true; DaysOfWeek = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"; At = "07:30" }
    },
    @{
        Name        = "Jarvis-DiskWatch"
        Description = "Weekly disk-usage watch with >2GB growth alerts"
        Worker      = "disk-watch.ps1"
        Args        = "-Top 15 -AlertGrowthMB 2048"
        TriggerArgs = @{ Weekly = $true; DaysOfWeek = "Monday"; At = "08:00" }
    },
    @{
        Name        = "Jarvis-ToolHealth"
        Description = "Weekly toolchain health check (Python venv, Node, pnpm, PATH)"
        Worker      = "tool-health.ps1"
        Args        = ""
        TriggerArgs = @{ Weekly = $true; DaysOfWeek = "Monday"; At = "08:15" }
    },
    @{
        Name        = "Jarvis-RepoRemoteCheck"
        Description = "Weekly repo-remote integrity check (no-remote + unreachable)"
        Worker      = "repo-remote-check.ps1"
        Args        = ""
        TriggerArgs = @{ Weekly = $true; DaysOfWeek = "Friday"; At = "17:00" }
    },
    @{
        Name        = "Jarvis-ArchiveRotate"
        Description = "Monthly inbox + loose-files rotation (Execute mode)"
        Worker      = "archive-rotate.ps1"
        Args        = "-Execute"
        TriggerArgs = @{ Monthly = $true; DaysOfMonth = 1; At = "02:00" }
    },
    @{
        Name        = "Jarvis-MemoryHygiene"
        Description = "Monthly MEMORY.md hygiene (line-count + broken-refs)"
        Worker      = "memory-hygiene.ps1"
        Args        = ""
        TriggerArgs = @{ Monthly = $true; DaysOfMonth = 1; At = "02:30" }
    },
    @{
        Name        = "Jarvis-VaultDriftCheck"
        Description = "Weekly Obsidian vault health check (file count, size, staleness, critical files)"
        Worker      = "vault-drift-check.ps1"
        Args        = ""
        TriggerArgs = @{ Weekly = $true; DaysOfWeek = "Sunday"; At = "09:30" }
    },
    @{
        Name        = "Jarvis-OrphanProcSweep"
        Description = "Hourly sweep of orphan shell/scan procs left by uncleanly-killed Claude Code sessions"
        Worker      = "sweep-orphan-claude-procs.ps1"
        Args        = "-Apply -MinAgeMinutes 30"
        TriggerArgs = @{ Hourly = $true; StartMinuteOffset = 17 }
    },
    @{
        Name        = "Jarvis-MemoryWatch"
        Description = "Every-15-min memory pressure watcher; alerts on low RAM, pagefile thrash, or commit exhaustion"
        Worker      = "memory-watch.ps1"
        Args        = "-Quiet -Notify"
        TriggerArgs = @{ Minutely = $true; IntervalMinutes = 15; StartMinuteOffset = 7 }
    }
)

function New-Trigger($triggerArgs) {
    if ($triggerArgs.Minutely) {
        # Fires once at today @ HH:MM then repeats every IntervalMinutes forever.
        $offset = [int]($triggerArgs.StartMinuteOffset)
        $intervalMin = [int]($triggerArgs.IntervalMinutes)
        $startAt = (Get-Date).Date.AddMinutes($offset)
        return New-ScheduledTaskTrigger -Once -At $startAt `
            -RepetitionInterval (New-TimeSpan -Minutes $intervalMin) `
            -RepetitionDuration ([TimeSpan]::FromDays(3650))
    }
    elseif ($triggerArgs.Hourly) {
        # Fires once at today @ HH:MM (offset minutes from midnight) then repeats every hour forever.
        # Using a static start time keeps the trigger deterministic across re-installs.
        $offset = [int]($triggerArgs.StartMinuteOffset)
        $startAt = (Get-Date).Date.AddMinutes($offset)
        return New-ScheduledTaskTrigger -Once -At $startAt `
            -RepetitionInterval (New-TimeSpan -Hours 1) `
            -RepetitionDuration ([TimeSpan]::FromDays(3650))  # ~10 years; effectively forever
    }
    elseif ($triggerArgs.Weekly) {
        return New-ScheduledTaskTrigger -Weekly -DaysOfWeek $triggerArgs.DaysOfWeek -At $triggerArgs.At
    }
    elseif ($triggerArgs.Monthly) {
        # PowerShell ScheduledTasks doesn't have a -Monthly flag on
        # New-ScheduledTaskTrigger, so build via CIM.
        $cls = Get-CimClass MSFT_TaskMonthlyTrigger root/Microsoft/Windows/TaskScheduler
        $trig = New-CimInstance -CimClass $cls -ClientOnly
        $trig.DaysOfMonth = $triggerArgs.DaysOfMonth
        $trig.MonthOfYear = 4095  # all 12 months bitmask (0x0FFF)
        $trig.StartBoundary = (Get-Date $triggerArgs.At -Format "yyyy-MM-ddTHH:mm:ss")
        $trig.Enabled = $true
        return $trig
    }
    else {
        throw "Unknown trigger type"
    }
}

foreach ($task in $tasks) {
    $taskName = $task.Name

    if ($Uninstall) {
        if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
            if (-not $DryRun) {
                Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
            }
            Write-Host "[UNINSTALL] $taskName" -ForegroundColor Yellow
        }
        else {
            Write-Host "[SKIP]      $taskName (not registered)" -ForegroundColor Gray
        }
        continue
    }

    $workerPath = Join-Path $ScriptsDir $task.Worker
    if (-not (Test-Path $workerPath)) {
        Write-Warning "Worker missing, skipping: $workerPath"
        continue
    }

    # Wrap each worker via notify-on-fail.ps1 so non-zero exits are captured
    # to ~/scripts/.regression-alerts.log + optional Telegram. The wrapper
    # preserves the worker's exit code so Task Scheduler last-result is honest.
    $notifyPath = Join-Path $ScriptsDir "notify-on-fail.ps1"
    $workerStem = [IO.Path]::GetFileNameWithoutExtension($task.Worker)
    $argLine = "-NoProfile -ExecutionPolicy Bypass -File `"$notifyPath`" -WorkerName `"$workerStem`""
    if ($task.Args) { $argLine += " -ExtraArgs `"$($task.Args)`"" }

    if ($DryRun) {
        Write-Host "[DRY-RUN]   $taskName" -ForegroundColor Cyan
        Write-Host "            powershell.exe $argLine"
        Write-Host "            trigger: $($task.TriggerArgs | ConvertTo-Json -Compress)"
        continue
    }

    if ($task.TriggerArgs.Monthly) {
        # CIM-built MSFT_TaskMonthlyTrigger is rejected by Register-ScheduledTask
        # on this Windows build (HRESULT 0x80070057 even with valid PSTypeName).
        # Fall back to schtasks.exe, which accepts monthly triggers cleanly.
        # Inner quotes are escaped \" so they survive cmd.exe arg-parsing.
        $escArg = $argLine -replace '"', '\"'
        $tr = "powershell.exe $escArg"
        $day = $task.TriggerArgs.DaysOfMonth
        $startTime = $task.TriggerArgs.At
        & schtasks.exe /Create /TN $taskName /TR $tr /SC MONTHLY /D $day /ST $startTime /RL LIMITED /F | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "schtasks.exe failed for $taskName (exit $LASTEXITCODE)"
            continue
        }

        # schtasks.exe doesn't expose StartWhenAvailable / MultipleInstances /
        # ExecutionTimeLimit / Description. Post-process via the PS module so
        # monthly tasks have the same protective settings as weekly ones.
        $monthlySettings = New-ScheduledTaskSettingsSet `
            -StartWhenAvailable `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
            -MultipleInstances IgnoreNew

        # Set-ScheduledTask doesn't expose -Description on Win 11 26200; the
        # description is best-effort and not load-bearing. Apply settings only.
        Set-ScheduledTask -TaskName $taskName `
            -Settings $monthlySettings | Out-Null
    }
    else {
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argLine
        $trigger = New-Trigger $task.TriggerArgs
        $settings = New-ScheduledTaskSettingsSet `
            -StartWhenAvailable `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
            -MultipleInstances IgnoreNew

        Register-ScheduledTask `
            -TaskName $taskName `
            -Description $task.Description `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -User $env:USERNAME `
            -RunLevel Limited `
            -Force | Out-Null
    }

    Write-Host "[OK]        $taskName" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== DONE ===" -ForegroundColor Cyan
if (-not $Uninstall -and -not $DryRun) {
    Write-Host "View:        Get-ScheduledTask -TaskName 'Jarvis-*' | ft TaskName,State"
    Write-Host "Test one:    Start-ScheduledTask -TaskName 'Jarvis-ScanCredentials'"
    Write-Host "Uninstall:   .\install-regression-tasks.ps1 -Uninstall"
}
