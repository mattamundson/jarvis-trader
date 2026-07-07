# JARVIS TRADER — Acceptance Checklist

Run this before declaring any task complete. Every item must be checked.

---

## TIER 0 — Safety (Always First)

These are non-negotiable. A task that breaks any of these is NOT complete — it is a regression.

```bash
# Run safety suite
cd engine && .venv/Scripts/python -m pytest tests/test_safety_layer.py -v
```

- [ ] `test_safety_layer.py` — all tests pass, none skipped
- [ ] `LIVE_TRADING_ENABLED = False` in `engine/config.py`
- [ ] `REQUIRE_HUMAN_APPROVAL = True` in `engine/config.py`
- [ ] Port 4001 still blocked in `engine/execution/ib_order_manager.py`
- [ ] `SafetyLayer.validate_order()` still runs 6 checks before any order
- [ ] No LLM output is used to make safety decisions anywhere in the change

---

## TIER 1 — Tests (Required)

```bash
cd engine && .venv/Scripts/python -m pytest tests/ -v
```

- [ ] All tests pass (0 failures, 0 errors)
- [ ] No tests were deleted or commented out
- [ ] New safety-related code has a corresponding test
- [ ] New agents or pipeline stages have a test in `test_pipeline_e2e.py`

---

## TIER 2 — Build and Types (Required)

```bash
cd dashboard && pnpm run build
```

- [ ] 16 routes compiled successfully
- [ ] 0 TypeScript errors
- [ ] No `any` types introduced

---

## TIER 3 — Secrets (Required before any push)

```bash
bash scripts/hooks/check-secrets.sh
```

- [ ] No new secrets detected
- [ ] No `.env` file staged
- [ ] No `client_secret*.json` staged
- [ ] No hardcoded API keys in any committed file

---

## TIER 4 — Coding Standards

**Python:**
- [ ] All functions ≤ 50 lines
- [ ] All files ≤ 400 lines (or ≤ 800 with justification)
- [ ] `logging.getLogger(__name__)` used — no `print()` in production code
- [ ] All endpoints have `try/except` → `HTTPException`
- [ ] Pydantic v2: `model_config = ConfigDict(...)`, `model_validate()`
- [ ] `ruff check` passes with 0 errors: `cd engine && .venv/Scripts/python -m ruff check .`

**TypeScript:**
- [ ] No `hardcoded localhost:8010` in any dashboard file
- [ ] All engine calls go through `fetchEngine` / `postEngine` in `lib/api.ts`
- [ ] `"use client"` added only where browser APIs or interactivity are required
- [ ] New response types defined in `dashboard/lib/api.ts`

---

## TIER 5 — Instrument and Signal Safety

If `engine/backtest/signals.py` was modified:
- [ ] `INSTRUMENT_PARAMS` changes are walk-forward validated
- [ ] MGC remains HALTED (WFE 0.14)
- [ ] MES remains DO NOT TRADE (WFE 0.09)
- [ ] MCL params: (OS=15, OB=83, STOP=0.90, T1=1.50, T2=2.618, T3=4.00)
- [ ] MNQ params: (OS=15, OB=92, STOP=0.70, T1=1.00, T2=1.80, T3=2.618)

---

## TIER 6 — Routing Integrity

If any new routers were added or routers were modified:

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_routes_wired.py -v
```

- [ ] All 24 routers still registered in `main.py`
- [ ] New router has `inject_dependencies()` called in `main.py` startup
- [ ] New router file has `router = APIRouter()` with `prefix=` and `tags=`
- [ ] New endpoints added to `COMMANDS.md` in the skill pack

---

## TIER 7 — Commit Quality

- [ ] Commit message follows conventional format (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`)
- [ ] Commit message accurately describes what changed
- [ ] No unrelated changes bundled into this commit
- [ ] PR/branch name matches task type

---

## TIER 8 — Documentation

For features that change observable behavior:
- [ ] `CLAUDE.md` updated if key files or architecture changed
- [ ] `COMMANDS.md` updated if new endpoints were added
- [ ] `ARCHITECTURE.md` updated if module boundaries changed
- [ ] Code-level docstrings updated for modified functions

---

## Final Gate

A task is DONE only when ALL tiers above are checked. If any item fails:

1. Do not mark the task complete.
2. Fix the issue.
3. Re-run the relevant tier checks.
4. Only proceed when the checklist is fully green.

---

## Quick Command Reference

```bash
# All engine tests
cd engine && .venv/Scripts/python -m pytest tests/ -v

# Safety only (most critical)
cd engine && .venv/Scripts/python -m pytest tests/test_safety_layer.py -v

# Dashboard type check
cd dashboard && pnpm run build

# Secrets check
bash scripts/hooks/check-secrets.sh

# Python linting
cd engine && .venv/Scripts/python -m ruff check .

# Safety invariants spot check
grep -n "LIVE_TRADING_ENABLED\|REQUIRE_HUMAN_APPROVAL" engine/config.py

# Port 4001 blocked check
grep -n "4001" engine/execution/ib_order_manager.py
```
