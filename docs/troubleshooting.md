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

**Symptom**: `netstat -ano | findstr ':8010'` shows 2+ LISTEN entries with different PIDs.

**Root cause**: Multiple orphaned uvicorn processes. Two common origins:
1. Failed `restart_engine.ps1` kills (legacy) — described below.
2. Mixing PM2 + manual `python -m uvicorn` launches — the manual one survives PM2 restarts and blocks future PM2 binds.

### 2026-04-14 incident (worst case observed)
A PowerShell-launched uvicorn from morning held port 8010. PM2's `jarvis-engine` could not bind, exited every ~30 seconds, restarted, exited again — **1,248 restart loops** with cmd windows flashing. Diagnosis chain:

```bash
pm2 list                                                           # ↺ counter climbing fast
netstat -ano | grep ":8010 "                                       # find owner PIDs
powershell "Get-CimInstance Win32_Process -Filter 'ProcessId=<X>' | Select CommandLine"
                                                                   # confirm it's a stray uvicorn
taskkill //PID <X> //F                                             # kill orphan
pm2 restart jarvis-engine                                          # clean start
```

### Defense in code (2026-04-16)
PM2 now launches the engine via `engine/scripts/port_guardian.py`, not uvicorn directly. The guardian runs a pre-flight: if port 8010 is held by a python/uvicorn process, it kills it before exec'ing uvicorn. Refuses to kill non-python processes (safety belt). See `engine/ecosystem.config.js`.

### Diagnosis (always-applicable)
```powershell
# Count listeners — should be 1
(netstat -ano | Select-String ':8010.*LISTEN').Count

# Find python processes by start time (oldest = original engine, others = orphans)
Get-Process python,python3,python3.12 -ErrorAction SilentlyContinue | Sort-Object StartTime | Select-Object Id,ProcessName,StartTime

# Map PID → command line (identify each instance's launch source)
Get-CimInstance Win32_Process -Filter "Name='python3.12.exe' OR Name='python.exe'" | Select-Object ProcessId,ParentProcessId,CommandLine | Format-List
```

### Manual fix (if guardian is bypassed)
1. `pm2 stop jarvis-engine`
2. `taskkill //PID <orphan> //F` for each non-PM2 listener
3. `pm2 start jarvis-engine`

**Note**: `python3.12.exe` from `WindowsApps\PythonSoftwareFoundation.Python.3.12_*` is the Microsoft Store Python. Even venv launches show this name because the venv `python.exe` is a thin launcher that exec's the base Python — the *packages* still come from the venv. Don't be alarmed by the Store path; the bug is duplicate processes, not which Python they use.

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
curl -s http://localhost:8010/safety/status -H "X-API-Key: ${JARVIS_API_KEY}" | python3 -c "import sys,json; d=json.load(sys.stdin); print('Kill switch:', d.get('kill_switch_active'))"

# 3. OpenClaw gateway alive?
wsl -d Ubuntu -e bash -c "openclaw gateway status 2>&1 | grep 'RPC probe'"

# 4. OpenClaw LLM working?
wsl -d Ubuntu -e bash -c "openclaw agent --agent main -m 'say ONLINE' --json 2>&1 | grep -o 'ONLINE'"

# 5. WhatsApp test
curl -s -X POST http://localhost:8010/notifications/whatsapp/test -H "X-API-Key: ${JARVIS_API_KEY}"
```

---

## OpenClaw "Headers Timeout Error" / no-reply on WhatsApp

**Symptom (gateway logs, WSL)**:
```
[agent/embedded] [llm-idle-timeout] ollama/qwen2.5:7b produced no reply before the idle watchdog; retrying same model
[agent/embedded] embedded run failover decision: ... stage=assistant decision=surface_error reason=timeout
```

**What it is NOT**: a network problem. `curl http://127.0.0.1:11434/api/tags` from WSL returns 200 OK. The 2026-04-16 handoff memo called it a "Headers Timeout Error" but that was mis-classification — it's OpenClaw's **internal LLM idle watchdog** firing before qwen2.5:7b streams its first token. On CPU-only Ollama, the model can take >120s to reach first-token for a large (35K-char OpenClaw) system prompt.

**Root cause**: `agents.defaults.llm.idleTimeoutSeconds` defaults to 120. Qwen2.5:7b on CPU routinely blows past that for WhatsApp-approval-sized prompts, so the watchdog aborts and OpenClaw falls back to surface_error.

**Fix** (WSL):
```bash
wsl -d Ubuntu -e openclaw config set agents.defaults.llm.idleTimeoutSeconds 300
wsl -d Ubuntu -e systemctl --user restart openclaw-gateway
```

**Verification**:
```bash
wsl -d Ubuntu -e openclaw config get agents.defaults.llm.idleTimeoutSeconds   # expect 300
wsl -d Ubuntu -e journalctl --user -u openclaw-gateway --since "5 min ago" | grep idle-timeout
```

**Permanent fix** if 300s still isn't enough: drop `agents.defaults.maxConcurrent` from 2 → 1 (less CPU contention), or switch OpenClaw's default model to a smaller quant (e.g. `qwen2.5:3b` or `phi3:mini`). The engine-side `/messaging/chat` path already uses direct Ollama and is not affected by this watchdog.

---

## OpenClaw secret-storage convention (2026-04-17)

**Principle**: API keys live in `/root/.openclaw/gateway.systemd.env` (mode 600), NOT inline in `models.json`. OpenClaw's schema supports env-var references for every provider's `apiKey` field:

```json
"apiKey": {
  "source": "env",
  "provider": "openai",
  "id": "OPENAI_API_KEY"
}
```

Current wiring (as of 2026-04-17):
- `models.providers.openai.apiKey` → env-ref, resolves `OPENAI_API_KEY`
- `models.providers.codex.apiKey` → env-ref, resolves `CODEX_API_KEY`
- `models.providers.anthropic.apiKey` → still plaintext (Anthropic key is provisioned differently via Claude Code; defer unless rotation becomes needed)
- `models.providers.ollama.apiKey` → plaintext dummy (Ollama has no real auth)

**Systemd wiring**:
- `EnvironmentFile=/root/.openclaw/gateway.systemd.env` on the `openclaw-gateway.service`
- `OPENCLAW_SERVICE_MANAGED_ENV_KEYS` includes `OPENAI_API_KEY,CODEX_API_KEY,OLLAMA_API_KEY,BRAVE_API_KEY,BRAVE_SEARCH_API_KEY` so OpenClaw merges them into provider resolution
- All three sensitive files (`gateway.systemd.env`, `models.json`, `auth-profiles.json`) are mode 600

**Rotating a key** (the part that has to be done manually):
1. Generate a new key on the provider's dashboard (e.g., platform.openai.com → API keys → Create new secret key)
2. Update the env file in place:
   ```bash
   wsl -d Ubuntu -e bash -c 'sed -i "s|^OPENAI_API_KEY=.*|OPENAI_API_KEY=<new-key>|" /root/.openclaw/gateway.systemd.env'
   wsl -d Ubuntu -e systemctl --user restart openclaw-gateway
   ```
3. Verify the new key is live:
   ```bash
   wsl -d Ubuntu -e bash -c 'GID=$(systemctl --user show openclaw-gateway -p MainPID --value); tr "\0" "\n" < /proc/$GID/environ | grep OPENAI_API_KEY | head -c 25'
   ```
4. Revoke the old key on the provider's dashboard

No need to touch `models.json` on rotation — env-ref indirection means the config is stable.

**Verification** the env-ref is working:
```bash
wsl -d Ubuntu -e bash -c 'python3 -c "
import json
m = json.load(open(\"/root/.openclaw/agents/main/agent/models.json\"))
for p in (\"openai\", \"codex\"):
    k = m[\"providers\"][p][\"apiKey\"]
    assert isinstance(k, dict) and k.get(\"source\") == \"env\", f\"{p} not env-ref: {k}\"
    print(f\"{p}: ok, env id={k[\"id\"]}\")
"'
```
