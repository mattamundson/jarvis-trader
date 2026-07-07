---
description: Snapshot the learning system state — IC-weighted analyst rankings, recent trade outcomes, pattern memory top entries, and AgentFeedbackTracker confidence per symbol. Read-only.
allowed-tools: Bash(curl:*), Read
argument-hint: "[symbol: MCL|MNQ|MES, default MCL]"
---

# Learning System Snapshot

**Symbol**: $ARGUMENTS (default `MCL`)

## Steps

Parallel curl calls:
```bash
API_KEY="${JARVIS_API_KEY}"
SYM="${ARGUMENTS:-MCL}"
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/learning/status"
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/learning/confidence/$SYM"
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/learning/patterns?symbol=$SYM&limit=10"
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/learning/suggestions?symbol=$SYM"
```

If any endpoint returns 503 or empty → note which one failed, continue with the rest.

## Output

```
## Learning Snapshot — <symbol> — <time>

### System status
- Patterns tracked: <n>
- Trades logged: <n>
- Last update: <iso>

### Confidence for <symbol>
- Current: <pct>
- Trend (last 5 trades): <up|flat|down>
- Sample size: <n>

### Top patterns (10 most recent updates)
1. <pattern_id> — win_rate <pct>, sample <n>, last_seen <date>
2. ...

### Suggestions
- <suggestion 1>
- <suggestion 2>
```

Close with a one-line interpretation:
- Confidence > 0.65 + ≥20 samples → `model has conviction`
- Confidence 0.45–0.65 → `mixed — rely on advisor`
- Confidence < 0.45 → `muted — do not size up`
- Sample size < 10 → `insufficient data — confidence not yet meaningful`

## Constraints

- Read-only. Do NOT call `POST /learning/memory` or `POST /learning/consolidate` from this command.
- If `/learning/status` reports `trades_logged: 0`, print `AgentFeedbackTracker empty — paper-trading hasn't started yet or DB was reset`. Don't pretend there's signal.

## Why this exists

Pattern source: `goldentrii/agentrecall` (memory/recall pattern — "recall before you act"). jarvis-trader has a full learning router (`/learning/status`, `/learning/confidence/{symbol}`, `/learning/patterns`, `/learning/suggestions` — all verified in `engine/routers/learning_router.py`) with IC-weighted ensemble + AgentFeedbackTracker behind it, but no command to pull the four relevant pieces in one shot for a pre-trade confidence read.
