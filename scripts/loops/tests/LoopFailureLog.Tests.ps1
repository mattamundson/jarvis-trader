#Requires -Modules @{ ModuleName = 'Pester'; ModuleVersion = '5.0.0' }
<#
.SYNOPSIS
  Regression coverage for the 2026-07-09 "failure reason evaporates on exit" bug
  class -- extended from the morning-brief-loop.ps1 fix (PR #338) to the other
  loop wrappers that share the exact same Stop-WithError shape.

.DESCRIPTION
  Before this fix, Stop-WithError in morning-framing-brief-loop.ps1,
  levels-calibrator-loop.ps1, and forecast-scorer-loop.ps1 only wrote an ERROR
  status to docs/loop-reports/.heartbeat and (best-effort) pushed a Discord
  notification -- if JARVIS_LOOP_WEBHOOK was unset or the webhook call failed,
  the actual failure reason string was never persisted anywhere durable. A
  Task-Scheduler-triggered run leaves no stdout/stderr capture, so the only
  trace of WHY a run failed was gone the instant the process exited.

  This test drives each affected script as a real child process (Stop-WithError
  calls `exit 3`, so it cannot be dot-sourced into the Pester host) against a
  deterministic failure precondition, and asserts:
    1. the process exits 3 (unchanged fail-closed behavior), and
    2. docs/loop-reports/<loop>.log now contains a line with a UTC timestamp
       and the actual reason text -- which would NOT exist before this fix.

  Each script is run against an isolated temp RepoRoot so no repo state
  (docs/loop-reports/.heartbeat, real webhook) is touched.
#>

BeforeAll {
    $script:LoopsDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    $script:Pwsh = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
    if (-not $script:Pwsh) { $script:Pwsh = (Get-Command powershell).Source }

    function Invoke-LoopScript {
        param(
            [Parameter(Mandatory)][string] $ScriptName,
            [Parameter(Mandatory)][string] $RepoRoot,
            [string[]] $ExtraArgs = @()
        )
        $scriptPath = Join-Path $script:LoopsDir $ScriptName
        $argList = @('-NoProfile', '-NonInteractive', '-File', $scriptPath, '-RepoRoot', $RepoRoot) + $ExtraArgs
        & $script:Pwsh @argList 2>&1 | Out-Null
        return $LASTEXITCODE
    }
}

Describe 'Loop failure-reason durability (2026-07-09 sweep)' {

    BeforeEach {
        $script:TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "loop-faillog-test-$([guid]::NewGuid().ToString('N'))"
        New-Item -ItemType Directory -Path $script:TempRoot -Force | Out-Null
    }

    AfterEach {
        Remove-Item -Path $script:TempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }

    Context 'morning-framing-brief-loop.ps1 (health-check failure path)' {
        It 'exits 3 and persists the failure reason to docs/loop-reports/morning-framing-brief.log' {
            $exitCode = Invoke-LoopScript -ScriptName 'morning-framing-brief-loop.ps1' `
                -RepoRoot $script:TempRoot `
                -ExtraArgs @('-HealthUrl', 'http://127.0.0.1:1/health')

            $exitCode | Should -Be 3

            $logPath = Join-Path $script:TempRoot 'docs\loop-reports\morning-framing-brief.log'
            Test-Path $logPath | Should -BeTrue -Because 'the failure reason must survive after the process exits'

            $lines = @(Get-Content -Path $logPath)
            $lines.Count | Should -BeGreaterOrEqual 1
            $lines[-1] | Should -Match '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\t.+'
            $lines[-1] | Should -Match 'engine unreachable'
        }
    }

    Context 'levels-calibrator-loop.ps1 (missing-venv failure path)' {
        It 'exits 3 and persists the failure reason to docs/loop-reports/levels-calibrator.log' {
            $exitCode = Invoke-LoopScript -ScriptName 'levels-calibrator-loop.ps1' -RepoRoot $script:TempRoot

            $exitCode | Should -Be 3

            $logPath = Join-Path $script:TempRoot 'docs\loop-reports\levels-calibrator.log'
            Test-Path $logPath | Should -BeTrue -Because 'the failure reason must survive after the process exits'

            $lines = @(Get-Content -Path $logPath)
            $lines.Count | Should -BeGreaterOrEqual 1
            $lines[-1] | Should -Match '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\t.+'
            $lines[-1] | Should -Match 'venv python missing'
        }
    }

    Context 'forecast-scorer-loop.ps1 (missing-venv failure path)' {
        It 'exits 3 and persists the failure reason to docs/loop-reports/forecast-scorer.log' {
            $exitCode = Invoke-LoopScript -ScriptName 'forecast-scorer-loop.ps1' -RepoRoot $script:TempRoot

            $exitCode | Should -Be 3

            $logPath = Join-Path $script:TempRoot 'docs\loop-reports\forecast-scorer.log'
            Test-Path $logPath | Should -BeTrue -Because 'the failure reason must survive after the process exits'

            $lines = Get-Content -Path $logPath
            $lines.Count | Should -BeGreaterOrEqual 1
            $lines[-1] | Should -Match '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\t.+'
            $lines[-1] | Should -Match 'venv python missing'
        }
    }
}
