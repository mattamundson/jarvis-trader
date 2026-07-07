---
description: One-shot kill-switch + safety snapshot. Queries /safety/status and /safety/loss-tracker/status, formats a human-readable summary, flags any drift from hardcoded caps. Read-only — never toggles the switch.
allowed-tools: Bash(curl:*), Read, Grep
argument-hint: "(no arguments — always full snapshot)"
---

# Kill-Switch Check

Single-purpose orchestrator: dump current kill-switch + daily-loss tracker state in one shot so Matt can eyeball before placing a trade or walking away.

## Steps

1. Fetch both status endpoints in parallel (single Bash message, two curls):
   ```bash
   API_KEY="${JARVIS_API_KEY}"
   curl -s -H "X-API-Key: $API_KEY" http://localhost:8010/safety/status
   curl -s -H "X-API-Key: $API_KEY" http://localhost:8010/safety/loss-tracker/status
   ```

2. If either returns non-200 or empty body, report "engine down or safety router unloaded" and STOP. Do not guess values.

3. Synthesize into this exact table:
   ```
   ## Kill-Switch Snapshot — <local time>

   | Field                     | Value                    |
   |---------------------------|--------------------------|
   | Kill switch active        | <true|false>             |
   | Reason                    | <reason or "—">          |
   | Daily P&L                 | $<x.xx>                  |
   | Daily limit               | $<x.xx> (<pct>)          |
   | Daily P&L %               | <pct>                    |
   | Orders last minute        | <n>                      |
   | Consecutive losses        | <n>                      |
   | Loss tracker halted       | <true|false>             |
   | Resume time               | <iso or "—">             |
   | Equity (current/peak)     | $<cur> / $<peak>         |
   | PnL source                | <memory|db|broker>       |
   ```

4. Append a one-line verdict:
   - `READY` — kill switch off, loss tracker not halted, daily P&L > 50% of limit buffer
   - `CAUTION` — daily P&L within 20% of limit OR consecutive_losses ≥ 2
   - `BLOCKED` — kill switch on OR loss tracker halted

## Hard constraints

- NEVER POST to `/safety/kill-switch/*`. This command is read-only.
- NEVER modify config.py, LIVE_TRADING_ENABLED, or any hardcoded cap.
- If you see `LIVE_TRADING_ENABLED=true` in the response anywhere without explicit owner override in session memory → print a loud `*** WARNING *** live trading flag is on` and include it in the verdict.

## Why this exists

Pattern source: `goldentrii/agentrecall` (the `/arstart` single-command context load) adapted to a trading safety snapshot. jarvis-trader had the endpoints (`/safety/status`, `/safety/loss-tracker/status` verified in `engine/routers/safety_router.py`) but no single slash invocation that formatted them for a human glance.
