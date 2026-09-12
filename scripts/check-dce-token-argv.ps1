<#
.SYNOPSIS
  Detect DiscordChatExporter token exposure through process command-line args.

.DESCRIPTION
  DiscordChatExporter supports DISCORD_TOKEN via environment variable. Passing
  `--token` or `-t <token>` leaks credentials through Win32_Process.CommandLine.
  This checker reports only counts/PIDs and never prints command lines or token
  values.

.EXITCODES
  0 = no unsafe live DCE argv detected / self-test passed
  2 = unsafe live DCE argv detected
  10 = self-test failed
#>
[CmdletBinding()]
param(
    [switch]$SelfTest
)

$ErrorActionPreference = 'Stop'

function Test-DceTokenArg {
    param([AllowNull()][string]$CommandLine)
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $false }

    # Match DCE's long token option and short -t token option only when they are
    # separate CLI switches. Do not match unrelated words containing '-t'.
    $patterns = @(
        '(?i)(^|\s)--token(\s|=)',
        '(?i)(^|\s)-t\s+\S+'
    )
    foreach ($p in $patterns) {
        if ($CommandLine -match $p) { return $true }
    }
    return $false
}

if ($SelfTest) {
    $cases = @(
        @{ Name = 'safe-env-token'; CommandLine = 'DiscordChatExporter.Cli.exe export --channel 123 --output C:\tmp\ --format Json'; Expected = $false },
        @{ Name = 'unsafe-long-token'; CommandLine = 'DiscordChatExporter.Cli.exe export --channel 123 --token fake-token --output C:\tmp\'; Expected = $true },
        @{ Name = 'unsafe-long-token-equals'; CommandLine = 'DiscordChatExporter.Cli.exe export --channel 123 --token=fake-token --output C:\tmp\'; Expected = $true },
        @{ Name = 'unsafe-short-token'; CommandLine = 'DiscordChatExporter.Cli.exe export -c 123 -t fake-token -o C:\tmp\'; Expected = $true },
        @{ Name = 'safe-respect-rate-limits'; CommandLine = 'DiscordChatExporter.Cli.exe export -c 123 --respect-rate-limits -o C:\tmp\'; Expected = $false }
    )

    $failed = @()
    foreach ($c in $cases) {
        $actual = Test-DceTokenArg $c.CommandLine
        if ($actual -ne $c.Expected) { $failed += $c.Name }
    }
    if ($failed.Count -gt 0) {
        Write-Output ("DCE_ARGV_SELFTEST_FAIL cases={0}" -f ($failed -join ','))
        exit 10
    }
    Write-Output 'DCE_ARGV_SELFTEST_OK cases=5'
    exit 0
}

$rows = @(Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -like 'DiscordChatExporter*') -or ($_.ExecutablePath -like '*DiscordChatExporter*')
})

$unsafe = @()
foreach ($r in $rows) {
    if (Test-DceTokenArg $r.CommandLine) {
        $unsafe += [pscustomobject]@{ ProcessId = $r.ProcessId; Name = $r.Name }
    }
}

if ($unsafe.Count -gt 0) {
    $pids = ($unsafe | ForEach-Object { $_.ProcessId }) -join ','
    Write-Output ("DCE_ARGV_SECRET_LEAK count={0} pids={1}" -f $unsafe.Count, $pids)
    exit 2
}

Write-Output ("DCE_ARGV_OK checked={0}" -f $rows.Count)
exit 0
