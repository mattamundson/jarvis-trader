---
description: Pre-trade go/no-go orchestrator. Run before placing any paper trade. Coordinates safety-reviewer + pipeline-debugger to verify signal confidence, risk caps, kill-switch state, and current P&L vs daily loss limit. Blocks trade on any red flag.
allowed-tools: Bash(curl:*), Read, Grep, Agent
argument-hint: "<symbol> <side: BUY|SELL> <contracts>"
---

# Pre-Trade Go/No-Go

**Inputs**: $ARGUMENTS

Refuse to proceed if argument count is not exactly 3. Required form: `<symbol> <side> <contracts>`.

## Orchestration

Dispatch these two agents in parallel (single message, multiple Agent calls):

1. **`safety-reviewer`** — ask: "verify: LIVE_TRADING_ENABLED state, kill-switch armed/tripped, current daily P&L, current open contracts for $1, remaining capital allocation for $1. Flag any of: (a) LIVE_TRADING_ENABLED=true without Matt's explicit override note, (b) kill-switch tripped, (c) daily P&L within 20% of MAX_DAILY_LOSS_PCT, (d) open contracts + requested $3 exceeds MAX_CONTRACTS_PER_INSTRUMENT=2, (e) symbol not in paper-approved set (MCL, MNQ, MES with bypass)."

2. **`pipeline-debugger`** — ask: "report most recent pipeline verdict for $1 within the last 15 minutes. Confirm: (a) debate score sign matches $2 ($2=BUY needs score>0, $2=SELL needs score<0), (b) |score| ≥ 0.05 threshold, (c) advisor verdict if consulted did not veto, (d) IC ensemble not in muted state for $1."

## Decision rule

```
if any safety-reviewer flag triggers:
    print "🚫 NO-GO — safety: <flag(s)>"
    exit

if any pipeline-debugger flag triggers:
    print "🚫 NO-GO — signal: <flag(s)>"
    exit

print "✅ GO — $2 $3 $1"
print "  debate_score: <score>"
print "  current P&L vs cap: $<x> / $<y>"
print "  remaining contracts: <n>"
```

## Constraints

- This command is READ-ONLY. Do not submit orders. Do not modify config. Do not toggle kill switches.
- If either subagent times out, default to NO-GO. Silence is not safety.

## Why this exists

Extracted from `shanraisshan/claude-code-best-practice` (orchestration pattern). The existing `safety_layer.py` gate runs at order-submission time, too late to cancel the debate cost if the trade was going to be vetoed. This command moves the veto check to decision time, aligned with the "one invocation, many agents" pattern.
