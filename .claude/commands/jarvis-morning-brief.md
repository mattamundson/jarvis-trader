---
description: Orchestrate a complete jarvis-trader morning brief — engine health, kill-switch state, last signal confidence, open positions, and go/no-go for the session. Implements the Command → Agent → Skill pattern from shanraisshan/claude-code-best-practice.
allowed-tools: Bash(curl:*), Read, Grep, Glob, Agent
argument-hint: "[optional: symbol like MCL, MNQ, MES — defaults to all paper-approved]"
---

# Morning Brief Orchestrator

You are orchestrating a jarvis-trader morning brief. Coordinate subagents in parallel — do not do the work yourself.

**Symbol filter**: $ARGUMENTS (default: MCL + MNQ, both paper-approved)

## Orchestration steps

1. **Engine health snapshot** (Bash, parallel-safe):
   ```bash
   curl -s http://localhost:8010/health | head -c 500
   netstat -ano | grep ":8010 "
   ```
   If `/health` returns non-200 or port 8010 has no listener → STOP and report "engine down". Do not proceed.

2. **Dispatch three subagents in parallel** (single message, multiple Agent tool calls):
   - `pipeline-debugger` — ask: "report last 3 pipeline runs for $ARGUMENTS, note any stage failures, last debate score, and final verdict"
   - `safety-reviewer` — ask: "verify all hardcoded safety limits in engine/config.py are intact, confirm LIVE_TRADING_ENABLED=false, confirm kill_switch state, report any drift"
   - `backtest-runner` — ask: "check last WFE snapshot for $ARGUMENTS against paper-approval thresholds (MCL≥0.82, MNQ≥0.57, MES≥0.20 if bypassed)"

3. **Synthesize** the three agent returns into this exact structure:
   ```
   ## JARVIS Morning Brief — <date> <time>

   ### 🩺 Engine
   - Status: <healthy|degraded|down>
   - IBKR connected: <yes|no>
   - Polygon futures blocklist: <active>
   - Last restart: <time>

   ### 🛑 Safety
   - LIVE_TRADING_ENABLED: <bool>
   - Kill switch: <armed|tripped>
   - Hardcoded limit drift: <none|list>
   - Daily P&L vs cap: <$X / $Y>

   ### 📊 Signals
   - Last debate verdict per symbol: <BUY/SELL/PASS, score>
   - IC weights (top 3 analysts): <...>
   - Advisor consulted: <yes/no, verdict>

   ### ✅ Go/No-Go
   - <symbol>: <GO|NO-GO> — <one-sentence reason>
   ```

4. **Do not** trigger any trades, modify code, or commit anything. This is read-only.

## Failure modes to handle explicitly

- Engine down → print the `netstat` output so Matt can see orphan-PID owner and kill it manually.
- WFE snapshot missing → flag "no recent backtest, run `.\restart_engine.ps1` then re-run this command".
- Subagent timeout → don't retry; report which one failed and surface partial brief.

## Why this command exists

Extracted from `shanraisshan/claude-code-best-practice` (the Command → Agent → Skill orchestration pattern, specifically the `weather-orchestrator` example). jarvis-trader had all three agents (pipeline-debugger, safety-reviewer, backtest-runner) but no single command to coordinate them — forcing Matt to invoke each manually every morning. This command collapses that to one slash invocation.
