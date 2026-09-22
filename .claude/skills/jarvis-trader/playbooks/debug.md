# Playbook: Debug / Investigation

Use for: errors, crashes, failing tests, unexpected behavior, tracing "why is X happening."

---

## External Tools for Debugging

Before starting, check which tools apply:

| Situation | Tool |
|---|---|
| Need structured debug workflow with LLM guidance | `engineering:debug` skill (invoke first) |
| Agent pipeline failure — need to trace execution | gstack `/investigate` |
| Need to read a log file | `mcp__Desktop_Commander__read_file` → `engine/logs/*.log` |
| Engine not running — need to start it | `mcp__Desktop_Commander__start_process` |
| Need to check a running process / port | `mcp__Desktop_Commander__list_processes` |
| Visual dashboard bug — need browser | gstack `/qa` at `http://localhost:3010` |
| Need to look up related issues in stored docs | `mcp__c1fc4002-5f49-5f9d-a4e5-93c4ef5d6a75__google_drive_search` |

---

## Step 1 — Reproduce

Before touching any code, reproduce the problem deterministically.

```bash
# Check if the engine starts cleanly
cd engine && .venv/Scripts/python -m uvicorn main:app --reload --port 8010

# Run the full test suite to see what's currently failing
cd engine && .venv/Scripts/python -m pytest tests/ -v 2>&1 | tail -40

# Run a targeted test
cd engine && .venv/Scripts/python -m pytest tests/test_safety_layer.py -v

# Check dashboard type errors
cd dashboard && pnpm run build 2>&1 | tail -20
```

If you cannot reproduce: document what the user reported and what you see instead. Do NOT proceed to fix something you cannot confirm is broken.

---

## Step 2 — Localize

Determine which layer the bug lives in:

```
Is it a crash on startup?
  → engine/main.py router wiring, or engine/config.py missing env var

Is it a wrong API response?
  → Find the router: engine/routers/<area>_router.py
  → Check the handler function
  → Check the service/agent it calls

Is it a dashboard rendering issue?
  → dashboard/app/<page>/page.tsx or the component it renders
  → Check what fetchEngine() call it makes
  → Confirm the engine endpoint returns the expected shape

Is it a safety / risk issue?
  → engine/risk/safety_layer.py — validate_order() 6 checks
  → engine/risk/pnl_monitor.py — daily loss threshold
  → engine/config.py — TradingConfig limits

Is it a signal / backtest issue?
  → engine/backtest/signals.py — INSTRUMENT_PARAMS
  → engine/backtest/indicators.py — STC, ATR, regime indicators

Is it a pipeline failure?
  → engine/agents/pipeline.py — analyze_and_decide()
  → Check pipeline_result["errors"] in the response
  → Individual agents: engine/agents/<name>.py
```

---

## Step 3 — Isolate

Narrow to the smallest failing unit:

```bash
# Check logs
cat engine/logs/*.log 2>/dev/null | tail -50

# Quick Python sanity check
cd engine && .venv/Scripts/python -c "from config import settings; print(settings.model_dump())"

# Test one specific module
cd engine && .venv/Scripts/python -m pytest tests/test_safety_layer.py -v -k "test_name"

# Check if an endpoint is reachable (engine must be running)
curl -s -H "X-API-Key: [REDACTED]" http://localhost:8010/health
```

---

## Step 4 — Diagnose Root Cause

Write the root cause in one sentence before writing any fix:

> "The bug is in `<file>:<function>` — it does X but should do Y because Z."

If you cannot write this sentence, you have not found the root cause yet.

---

## Step 5 — Fix (Minimal Patch)

Rules:
- Fix only what is broken. Do not refactor adjacent code.
- If the fix touches `safety_layer.py`, STOP and request Tier 3 confirmation.
- If the fix changes `signals.py INSTRUMENT_PARAMS`, STOP and request walk-forward validation.
- File size limit: 400 lines typical, 800 absolute max.
- Function size limit: 50 lines max.
- No `print()` — use `logging.getLogger(__name__)`.

---

## Step 6 — Verify

```bash
# Must pass before declaring done
cd engine && .venv/Scripts/python -m pytest tests/ -v

# Safety layer must always pass
cd engine && .venv/Scripts/python -m pytest tests/test_safety_layer.py -v

# Dashboard must build clean
cd dashboard && pnpm run build
```

---

## Step 7 — Document

In the commit message and in code comments:

- What was the symptom?
- What was the root cause?
- What did you change?
- What regression risk remains?

Commit format: `fix: <short description of what was broken>`

---

## Deliverable

```
symptom:       <what the user reported>
root cause:    <file:function — what was wrong>
fix:           <what was changed and why>
verification:  <which tests now pass>
residual risk: <anything that could still go wrong>
```
