#!/usr/bin/env bash
# SessionStart hook — detect orphan uvicorn holding port 8010 before PM2 restart
# races into the crash-loop documented in MEMORY.md (PM2 port-conflict bug class,
# 2026-04-14 incident — 1,248 restart crash-loop).
#
# Read-only. Prints a warning if an orphan is detected; does NOT kill anything.
# Matt decides whether to taskkill based on the output.

set -u

port_owner=$(netstat -ano 2>/dev/null | grep -E ":8010\s" | awk '{print $5}' | head -1 || true)

if [[ -z "${port_owner}" ]]; then
    # Port free — engine not running. Normal case if PM2 is down.
    exit 0
fi

# Check if the owner PID is managed by PM2 (process name jarvis-engine) vs. an orphan.
# PM2-managed uvicorn runs under node's supervisor; orphans are standalone python3.12.exe.
if command -v powershell.exe >/dev/null 2>&1; then
    proc_info=$(powershell.exe -NoProfile -Command "Get-Process -Id ${port_owner} 2>\$null | Select-Object -ExpandProperty ProcessName" 2>/dev/null | tr -d '\r\n')
    if [[ "${proc_info}" == "python3.12" || "${proc_info}" == "python" ]]; then
        echo ""
        echo "⚠️  Port 8010 held by unmanaged Python PID ${port_owner} (${proc_info})."
        echo "    If PM2 restart fails, this is the orphan. Kill with:"
        echo "      taskkill //PID ${port_owner} //F"
        echo "    Then: pm2 restart jarvis-engine"
        echo ""
    fi
fi

exit 0
