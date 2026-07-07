---
description: IB Gateway (paper port 4002) connectivity check. Verifies the gateway is listening, the engine has a live IBKR connection, and the paper account matches DUP662235. Read-only.
allowed-tools: Bash(curl:*), Bash(netstat:*), Read
argument-hint: "(no arguments)"
---

# IB Gateway Health

## Steps

1. Port listener check:
   ```bash
   netstat -ano | grep ":4002 "
   ```
   - Empty output → gateway not running. Report: "IB Gateway not listening on 4002 — launch paper gateway before trading."
   - Output present → note the owning PID.

2. Engine broker status:
   ```bash
   API_KEY="${JARVIS_API_KEY}"
   curl -s -H "X-API-Key: $API_KEY" http://localhost:8010/brokers/status
   ```

3. Confirm paper account DUP662235 is the active account in the response. If it shows a live account or blank, flag it.

4. Confirm port 4001 (live) is NOT listening — it must remain PERMANENTLY BLOCKED:
   ```bash
   netstat -ano | grep ":4001 "
   ```
   - Any output → print `*** CRITICAL *** port 4001 is bound, live IBKR gateway must not be running in this environment`

## Output

```
## IB Gateway Health

- Paper port 4002: <listening|not listening>   PID: <n or —>
- Live port 4001: <not listening ✓ | BOUND ✗>
- Engine broker status: <connected|disconnected>
- Active account: <DUP662235|other>
- Last heartbeat: <iso if available>

Verdict: <READY|DEGRADED|BLOCKED>
```

Verdict rules:
- READY = 4002 listening, 4001 not listening, engine connected, account=DUP662235
- DEGRADED = 4002 listening but engine not connected (gateway up, handshake failed)
- BLOCKED = 4002 not listening OR 4001 listening OR account mismatch

## Constraints

- Never attempt to start/stop IB Gateway from this command. If down, tell Matt to launch manually.
- If port 4001 shows as bound, print the loud warning above but do NOT kill the process — let Matt triage.

## Why this exists

Pattern source: `shanraisshan/claude-code-best-practice` (health-check-before-orchestration pattern). jarvis-trader has `/brokers/status` (verified at `engine/routers/brokers_router.py:136`) plus the strong user-memory invariant that port 4001 must never be bound. This command codifies both checks into a single invocation.
