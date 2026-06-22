#Requires -Version 5.1
<#
  Pester tests for the engine-watchdog restart-storm guard (Test-EngineLogFresh).
  Regression cover for the 2026-06-18 restart storm: /health starves under RTH
  load and returns 000; the watchdog must SKIP the kill when the engine log is
  fresh (loop alive) and only restart when the log is genuinely stale.

  Run (Pester 3.x, ships with Windows):
    Invoke-Pester -Path scripts\tests\engine-watchdog-guards.Tests.ps1

  Mutation check: flip `-lt` to `-gt` in Test-EngineLogFresh and the
  "fresh log" cases below go red -- proves the guard direction is asserted.
#>

. (Join-Path $PSScriptRoot '..\lib\engine-watchdog-guards.ps1')

Describe 'Test-EngineLogFresh' {

    $base = Get-Date '2026-06-21T12:00:00'

    function New-LogFile([datetime]$WriteTime) {
        $p = Join-Path $TestDrive ('engine-error-{0}.log' -f ([guid]::NewGuid().ToString('N')))
        Set-Content -Path $p -Value 'log line'
        (Get-Item $p).LastWriteTime = $WriteTime
        return $p
    }

    Context 'engine log is fresh (loop alive -> SKIP restart)' {
        It 'reports Fresh when the log was written 10s ago (< 60s window)' {
            $log = New-LogFile $base
            $r = Test-EngineLogFresh -LogPath $log -ThresholdSec 60 -Now $base.AddSeconds(10)
            $r.Statted | Should Be $true
            $r.Fresh   | Should Be $true
            [math]::Abs($r.AgeSec - 10) | Should BeLessThan 1
        }

        It 'reports Fresh just under the boundary (59s)' {
            $log = New-LogFile $base
            $r = Test-EngineLogFresh -LogPath $log -ThresholdSec 60 -Now $base.AddSeconds(59)
            $r.Fresh | Should Be $true
        }
    }

    Context 'engine log is stale (genuine hang -> CONFIRM-DEAD, restart)' {
        It 'reports NOT Fresh when the log is 120s old' {
            $log = New-LogFile $base
            $r = Test-EngineLogFresh -LogPath $log -ThresholdSec 60 -Now $base.AddSeconds(120)
            $r.Statted | Should Be $true
            $r.Fresh   | Should Be $false
        }

        It 'treats exactly ThresholdSec as NOT fresh (strict less-than)' {
            $log = New-LogFile $base
            $r = Test-EngineLogFresh -LogPath $log -ThresholdSec 60 -Now $base.AddSeconds(60)
            $r.Fresh | Should Be $false
        }
    }

    Context 'log cannot be stat (missing/locked -> fail-safe restart)' {
        It 'returns Statted=$false and Fresh=$false for a missing file' {
            $missing = Join-Path $TestDrive 'does-not-exist.log'
            $r = Test-EngineLogFresh -LogPath $missing -ThresholdSec 60 -Now $base
            $r.Statted | Should Be $false
            $r.Fresh   | Should Be $false
        }
    }

    Context 'threshold is honoured' {
        It 'a 90s-old log is fresh under a 120s threshold' {
            $log = New-LogFile $base
            $r = Test-EngineLogFresh -LogPath $log -ThresholdSec 120 -Now $base.AddSeconds(90)
            $r.Fresh | Should Be $true
        }
    }
}
