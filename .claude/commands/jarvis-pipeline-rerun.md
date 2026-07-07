---
description: Re-run the 10-agent pipeline for a symbol and report the verdict. Uses /pipeline/run/sdk. Blocks if engine down or kill-switch tripped. Non-destructive — never places an order.
allowed-tools: Bash(curl:*), Read
argument-hint: "<symbol: MCL|MNQ|MES> [timeframe: 1h|4h|1d, default 1h]"
---

# Pipeline Re-Run

**Inputs**: $ARGUMENTS

Parse `<symbol> [timeframe]`. Default timeframe = `1h`. Refuse if symbol missing or not in `{MCL, MNQ, MES}`.

## Pre-flight (must pass before firing pipeline)

Single Bash message, parallel:
```bash
API_KEY="${JARVIS_API_KEY}"
curl -s http://localhost:8010/health
curl -s -H "X-API-Key: $API_KEY" http://localhost:8010/safety/status
```

- Engine down → STOP, print "engine down, re-run blocked"
- Kill switch active → STOP, print "kill switch active: <reason>, re-run blocked"

## Fire pipeline

```bash
API_KEY="${JARVIS_API_KEY}"
curl -s -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d "{\"symbol\":\"<symbol>\",\"timeframe\":\"<timeframe>\"}" \
  http://localhost:8010/pipeline/run/sdk
```

Expect ~250s latency for SDK path. If no response in 5 minutes, abort and report timeout.

## Report

```
## Pipeline Re-Run — <symbol> <timeframe>

- Run ID: <id>
- Duration: <sec>
- Debate score: <value>  (threshold: 0.05)
- Verdict: <BUY|SELL|PASS>
- Advisor consulted: <yes|no> — <verdict if yes>
- Top 3 IC-weighted analysts: <list>
- Cost: $<x.xx>
```

## Constraints

- Calls `/pipeline/run/sdk` which is a dry-run pipeline. It produces a verdict but does NOT submit an order.
- Never chain to a trade-placement endpoint. If Matt wants to act on the verdict, he runs `/jarvis-pretrade-check` next, then places the trade manually.
- If the endpoint 404s, fall back to `POST /pipeline/run` (the legacy non-SDK path) and note the fallback in the report.

## Why this exists

Pattern source: `hkuds/vibe-trading` (their CLI's one-command backtest+debate invocation). jarvis-trader has `/pipeline/run/sdk` (verified at `engine/routers/pipeline_router.py:750`) but invoking it required remembering the API key, symbol format, and the 250s wait — this command wraps all of that with the safety pre-flight the endpoint itself does not enforce.
