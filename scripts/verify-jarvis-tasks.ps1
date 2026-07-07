$tasks = @("Jarvis-ScanCredentials", "Jarvis-ScanUncommitted", "Jarvis-DiskWatch", "Jarvis-ToolHealth", "Jarvis-RepoRemoteCheck", "Jarvis-ArchiveRotate", "Jarvis-MemoryHygiene", "Jarvis-VaultDriftCheck")

$results = @()
foreach ($task in $tasks) {
    $sched = Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue

    if ($sched) {
        $info = $sched | Get-ScheduledTaskInfo
        $results += [PSCustomObject]@{
            Name               = $task
            State              = $sched.State
            LastRunTime        = if ($info.LastRunTime) { $info.LastRunTime.ToString("yyyy-MM-dd HH:mm") } else { "Never" }
            LastResult         = $info.LastTaskResult
            NextRunTime        = if ($info.NextRunTime) { $info.NextRunTime.ToString("yyyy-MM-dd HH:mm") } else { "N/A" }
            MissedRuns         = $info.NumberOfMissedRuns
            StartWhenAvailable = $sched.Settings.StartWhenAvailable
            MultipleInstances  = $sched.Settings.MultipleInstances
        }
    }
    else {
        $results += [PSCustomObject]@{
            Name               = $task
            State              = "NOT FOUND"
            LastRunTime        = "N/A"
            LastResult         = "N/A"
            NextRunTime        = "N/A"
            MissedRuns         = "N/A"
            StartWhenAvailable = "N/A"
            MultipleInstances  = "N/A"
        }
    }
}

$results | Format-Table -AutoSize -Wrap
