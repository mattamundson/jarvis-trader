# JARVIS Trader — Troubleshooting Guide

> **READ THIS FIRST** when diagnosing system issues. Updated as new root causes are confirmed.

---

## OpenClaw Not Responding in WhatsApp

**Symptom**: WhatsApp returns "⚠️ Something went wrong while processing your request."

**Root cause**: OpenClaw caches a `disabledUntil` lockout (up to 5 hours) when an API billing error occurs. Credits being restored does NOT clear the cache — it persists across gateway restarts.

**Diagnosis**:
```bash
wsl -d Ubuntu -e bash -c "grep -i 'billing\|rate_limit\|All models failed' /tmp/openclaw/openclaw-2026-04-06.log | tail -5"
```

**Fix** (run after topping up credits):
```bash
wsl -d Ubuntu -e python3 /mnt/c/Users/mattm/ThinkorSwim/jarvis-trader/scripts/fix-openclaw-lockout.py
wsl -d Ubuntu -e systemctl --user restart openclaw-gateway.service
```

Script location: `scripts/fix-openclaw-lockout.py`

**Verify** OpenClaw is working:
```bash
wsl -d Ubuntu -e bash -c "openclaw agent --agent main -m 'reply with the single word ONLINE' --json 2>&1 | grep -o 'ONLINE'"
```

---

## Engine WhatsApp Notifications Failing

**Symptom**: `POST /notifications/whatsapp/test` returns `{"status":"failed","sent":false}`.

**Common causes**:
1. `WHATSAPP_TO` is still the placeholder `whatsapp:+1XXXXXXXXXX` — never set
2. `TWILIO_ACCOUNT_SID` starts with `SK` (API Key SID) instead of `AC` (Account SID)
3. Engine not restarted after `.env` changes

**Fix**: Update `engine/.env`:
```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx   # must start AC, not SK
WHATSAPP_TO=whatsapp:+16128771189                       # your actual number
```
Then restart engine (see below).

**Verify Twilio credentials**: Get real Account SID from https://console.twilio.com (dashboard homepage).

---

## Engine Restart Failing

**Symptom**: `.\restart_engine.ps1` says "Could not replace listener(s)" and exits 0 without restarting.

**Root cause**: The engine process (uvicorn) runs as an elevated user. Normal `taskkill` from a non-admin session fails silently. The script has a bug: if `/health` returns 200 after failed kills, it exits successfully without actually restarting.

**Process archaeology** (multiple zombie instances accumulate after failed restart attempts):
- Port 8010 shows multiple LISTEN entries in `netstat -ano`
- PIDs in netstat don't match any visible Windows process — they're from elevated/hidden sessions
- The real engine process is the `python.exe` that has been running longest (started ~1:55 AM on the session start day)

**Fix**:
```
Option 1 (recommended): Task Manager as Admin
  → Ctrl+Shift+Esc → Run as administrator
  → Sort by Name → find python.exe started earliest today
  → End Task → then run .\restart_engine.ps1

Option 2: Admin PowerShell
  → Right-click PowerShell → Run as Administrator
  → cd C:\Users\mattm\ThinkorSwim\jarvis-trader
  → .\restart_engine_admin.ps1   (accept UAC prompt)
```

**After restart, verify**:
```bash
curl -s http://localhost:8010/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('uptime:', round(d['uptime_seconds'],1), 's')"
# uptime should be < 30s if restart succeeded
```

---

## Claude Code Stop Hook Error (Bun ENOENT)

**Symptom**: Every session end shows:
```
Stop hook error: Failed with non-blocking status code
Failed to start Bun: spawn bun ENOENT
```

**Root cause**: The `claude-mem` plugin requires Bun runtime. `smart-install.js` failed to install it, leaving Stop/PostToolUse hooks broken. Memory capture doesn't work until fixed.

**Fix** (one-time):
```powershell
irm bun.sh/install.ps1 | iex
```
Installs to `~/.bun/bin/bun.exe`. The `bun-runner.js` checks this path automatically — no PATH changes or restart needed.

**Status**: Fixed 2026-04-07. If error reappears, re-run the install command above.

---

## Duplicate Process Accumulation on Port 8010

**Symptom**: `netstat -ano | findstr ':8010'` shows 5+ LISTEN entries with phantom PIDs.

**Root cause**: Multiple orphaned uvicorn restarts. Each failed kill attempt in `restart_engine.ps1` leaves the old process running, then starts a new one. After N restart attempts, N uvicorn instances are running.

**Diagnosis**:
```powershell
# Count listeners
(netstat -ano | Select-String ':8010.*LISTEN').Count

# Find real python processes (sorted oldest first = engine)
Get-Process python,python3 -ErrorAction SilentlyContinue | Sort-Object StartTime | Select-Object Id,StartTime
```

**Fix**: Kill the oldest python.exe (started at session-start time) via Task Manager as Admin. The phantom PIDs in netstat are OS artifacts from elevated processes — they'll clear when the real process is killed.

---

## Key File Locations

| File | Purpose |
|------|---------|
| `engine/.env` | All secrets — Twilio, Anthropic, IBKR, etc. |
| `scripts/fix-openclaw-lockout.py` | Clear OpenClaw LLM provider lockout cache |
| `restart_engine.ps1` | Standard engine restart (requires admin if process is elevated) |
| `restart_engine_admin.ps1` | Admin restart via UAC prompt |
| `docs/engine-restart-checklist.md` | Pre-existing restart checklist |
| WSL: `/tmp/openclaw/openclaw-YYYY-MM-DD.log` | OpenClaw gateway logs |
| WSL: `/root/.openclaw/agents/main/agent/auth-profiles.json` | OpenClaw LLM provider state (billing lockouts here) |

---

## Quick Diagnostics Checklist

```bash
# 1. Engine alive?
curl -s http://localhost:8010/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('UP, uptime:', round(d['uptime_seconds']/3600,1), 'hrs')"

# 2. Kill switch?
curl -s http://localhost:8010/safety/status -H "X-API-Key: xPRdYjkyUP20r29jrhAlgefneE1oYGSvFn3ri5C1OGc" | python3 -c "import sys,json; d=json.load(sys.stdin); print('Kill switch:', d.get('kill_switch_active'))"

# 3. OpenClaw gateway alive?
wsl -d Ubuntu -e bash -c "openclaw gateway status 2>&1 | grep 'RPC probe'"

# 4. OpenClaw LLM working?
wsl -d Ubuntu -e bash -c "openclaw agent --agent main -m 'say ONLINE' --json 2>&1 | grep -o 'ONLINE'"

# 5. WhatsApp test
curl -s -X POST http://localhost:8010/notifications/whatsapp/test -H "X-API-Key: xPRdYjkyUP20r29jrhAlgefneE1oYGSvFn3ri5C1OGc"
```
