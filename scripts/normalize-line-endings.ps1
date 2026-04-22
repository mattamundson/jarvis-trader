#Requires -Version 5.1
<#
.SYNOPSIS
  Renormalize tracked files to match .gitattributes (LF for most text).

.DESCRIPTION
  Run from repo root after .gitattributes is committed. Expect a large diff.
  Then: git commit -m "fix: normalize line endings to LF"

  See: https://git-scm.com/docs/gitattributes
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
Write-Host "Repo root: $root"
Write-Host "Running: git add --renormalize ."
git add --renormalize .
Write-Host "Done. Review with: git status"
git status --short | Select-Object -First 40
