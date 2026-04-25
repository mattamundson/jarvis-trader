# pm2-restart-monitor.ps1 — writes 72h restart count for jarvis-engine to a sidecar JSON.
# Run on a schedule (e.g., every 15 min) or manually before gate check.

$outPath = "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\data\pm2_restart_count_72h.json"

$restarts = -1
$matchedName = ""
try {
    # pm2 may live behind npm-shim batchfile on Windows — prefer cmd /c shim.
    # -AsHashtable required because pm2_env carries env-var dict with case-clashing
    # keys (USERNAME vs username) that PSCustomObject conversion rejects.
    $raw = cmd /c "pm2 jlist" 2>$null
    if ($raw) {
        $data = $raw | ConvertFrom-Json -AsHashtable
        # Accept either "jarvis-engine" (plan-canonical) or "jarvis" (actual on this host).
        $engine = $data | Where-Object { $_["name"] -in @("jarvis-engine", "jarvis") } | Select-Object -First 1
        if ($engine -and $engine["pm2_env"]) {
            $restarts = [int]$engine["pm2_env"]["restart_time"]
            $matchedName = [string]$engine["name"]
        }
    }
} catch {
    $restarts = -1
}

$out = [pscustomobject]@{
    restarts_72h  = $restarts
    process_name  = $matchedName
    sampled_at    = (Get-Date -Format "o")
    note          = "pm2 lifetime restart count (proxy for 72h — reset pm2 to get a clean window)"
} | ConvertTo-Json

Set-Content -Path $outPath -Value $out -Encoding UTF8
Write-Host "Written: $outPath (process=$matchedName restarts=$restarts)"
