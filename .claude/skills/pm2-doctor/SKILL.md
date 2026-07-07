---
name: pm2-doctor
description: Diagnose and fix PM2 port-8010 orphan uvicorn process class for jarvis-trader engine. Use when the user reports "engine won't start", "port 8010 in use", "PM2 restart crash-loop", "engine keeps restarting", "1248 restarts", "EADDRINUSE 8010", "uvicorn orphan", "cannot bind", "port-8010 conflict", or when `pm2 logs jarvis-engine` shows repeated startup failures. Also trigger on any engine health check returning connection-refused while `pm2 status` shows the engine "online".
---

# When to use

This skill activates on the specific PM2 failure mode documented in MEMORY.md (2026-04-14 incident). Symptoms:

- `pm2 status` shows `jarvis-engine` as `online` or with high restart count (100+)
- `curl http://localhost:8010/health` returns connection-refused
- `pm2 logs jarvis-engine --lines 50` shows `[Errno 10048] Only one usage of each socket address`
- `netstat -ano | grep ":8010 "` shows an owner PID that is NOT the PM2-managed process

Root cause: orphaned Store Python `python3.12.exe` uvicorn process survives PM2 restarts and holds port 8010. PM2 then spawns a new process that cannot bind, crashes, restarts, and loops.

# How to use

Run the diagnosis steps in order. Do NOT blindly kill port owners — verify they are orphans first.

## Step 1 — Confirm symptom

```bash
pm2 status jarvis-engine
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8010/health
pm2 logs jarvis-engine --lines 30 --nostream
```

If PM2 reports online but health returns 000 (refused) or the logs show socket-address errors, proceed.

## Step 2 — Identify port owner

```bash
netstat -ano | grep ":8010 "
```

Record the PID in the rightmost column. Then:

```bash
powershell "Get-Process -Id <PID> | Format-List Id,ProcessName,Path,StartTime"
```

Confirm: ProcessName is `python3.12` or `python` AND Path contains `WindowsApps` or `Microsoft\WindowsApps` (Store Python) OR the StartTime predates the most recent `pm2 restart`. That is the orphan signature.

## Step 3 — Kill orphan and restart

```bash
taskkill //PID <PID> //F
pm2 restart jarvis-engine
pm2 logs jarvis-engine --lines 20 --nostream
curl -s http://localhost:8010/health
```

Expect health to return 200 within ~5 seconds.

## Step 4 — If restart still loops

The in-repo defense is `engine/scripts/port_guardian.py` (Roadmap T1.2/T2.4). If that script exists, run it pre-start:

```bash
python engine/scripts/port_guardian.py --port 8010 --kill-orphans
pm2 restart jarvis-engine
```

If it does not exist yet, escalate to admin restart:

```bash
powershell -File "C:/Users/mattm/ThinkorSwim/jarvis-trader/restart_engine_admin.ps1"
```

# Example

User: "engine is down, health check hangs"

1. `pm2 status jarvis-engine` -> online, restarts: 847
2. `netstat -ano | grep ":8010 "` -> `TCP 0.0.0.0:8010 ... LISTENING 14528`
3. `Get-Process -Id 14528` -> `python3.12`, path in `WindowsApps\` -> ORPHAN
4. `taskkill //PID 14528 //F` -> SUCCESS
5. `pm2 restart jarvis-engine` -> online, restarts reset
6. `curl http://localhost:8010/health` -> 200 OK

# Hard rules

- NEVER kill a PID whose parent is the PM2 daemon — that is the legitimate process, killing it just gives PM2 another restart to log.
- NEVER use `--reload` on `pm2 restart` (known to cause duplicate IB connections per MEMORY.md).
- If `restart_engine.ps1` fails three times, escalate to `restart_engine_admin.ps1` — do not keep retrying the non-admin script.
