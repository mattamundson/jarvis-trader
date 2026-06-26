<#
.SYNOPSIS
  Launch the jarvis-trader dashboard hot-reload dev server for Cursor editing.

.DESCRIPTION
  Runs `next dev` on port 3011 so it sits ALONGSIDE the pm2 production dashboard
  (port 3010) without colliding. Edit any file and the browser at :3011 updates
  instantly -- no build, no pm2 restart.

  API calls proxy to the engine at 127.0.0.1:8010 via next.config.ts rewrites;
  auth comes from dashboard/.env.local (NEXT_PUBLIC_ENGINE_API_KEY).

  Promote changes to the live (3010) dashboard with:
    pnpm build ; pm2 restart jarvis-dashboard

.PARAMETER Port
  Dev server port. Default 3011 (do not use 3010 -- that is the prod dashboard).

.PARAMETER Open
  Also open the dev URL in the default browser.

.EXAMPLE
  ./dev-cursor.ps1
  ./dev-cursor.ps1 -Open
#>
[CmdletBinding()]
param(
    [int]    $Port = 3011,
    [switch] $Open
)

$ErrorActionPreference = "Stop"
$dashboard = Split-Path -Parent $PSCommandPath
Set-Location $dashboard

if ($Port -eq 3010) {
    throw "Port 3010 is the pm2 production dashboard. Use 3011 (default) for dev."
}

Write-Host "[dev-cursor] next dev -> http://127.0.0.1:$Port  (prod stays on 3010)"
Write-Host "[dev-cursor] edits hot-reload; promote with: pnpm build ; pm2 restart jarvis-dashboard"

if ($Open) { Start-Process "http://127.0.0.1:$Port" }

# pnpm resolves the local next binary; run inline (not via Start-Process) so the
# .cmd shim is found and Ctrl-C stops the server cleanly.
pnpm exec next dev --port $Port
