# Playbook: Refactor

Use for: code cleanup, extracting modules, reducing file size, improving naming, reorganizing structure without changing behavior.

---

## Prime Directive

A refactor changes the code without changing the behavior. If tests start failing, you changed behavior — that is a bug, not a refactor. Revert and retry.

---

## Step 1 — Define Scope

Before touching anything:

1. State exactly what will be refactored (file, function, module, pattern).
2. State what will NOT change (behavior, API contracts, safety parameters).
3. Confirm no safety-critical files are in scope:
   - `engine/risk/safety_layer.py` → Tier 3 confirmation required
   - `engine/backtest/signals.py` INSTRUMENT_PARAMS → walk-forward validation required
   - `engine/config.py` risk limits → code review required

---

## Step 2 — Establish a Baseline

Run tests before writing a single line:

```bash
cd engine && .venv/Scripts/python -m pytest tests/ -v 2>&1 | tee /tmp/before_refactor.txt
cd dashboard && pnpm run build 2>&1 | tee /tmp/before_build.txt
```

Save these baselines. Any test that fails after your refactor that passed before is a regression you introduced.

---

## Step 3 — Identify the Refactor Type

| Type | Approach |
|---|---|
| File too large (>400 lines) | Extract by responsibility — keep public API identical |
| Function too large (>50 lines) | Extract private helpers within same file |
| Duplicate code across files | Extract to `engine/utils/` or a shared module |
| Bad naming | Rename with grep to find all usages first |
| Import cleanup | Use ruff to identify unused imports |
| TypeScript `any` types | Find interface definition, replace with typed imports |

---

## Step 4 — Plan the Extract

If splitting a large file, design the boundary first:

```
engine/routers/big_router.py  (current: 600 lines)
→ engine/routers/area_router.py        (endpoints only, ~150 lines)
→ engine/services/area_service.py      (business logic, ~200 lines)
→ engine/schemas/area_schemas.py       (Pydantic models, ~100 lines)
```

Ensure `main.py` still imports the same `router` name — don't change public API.

---

## Step 5 — Execute in Small Steps

Refactor one module at a time. After each step:

```bash
cd engine && .venv/Scripts/python -m pytest tests/ -v
```

Never accumulate multiple refactors before testing. If a step breaks tests, revert that step before continuing.

---

## Step 6 — Check Coding Standards

```bash
# Python: ruff check
cd engine && .venv/Scripts/python -m ruff check . 2>&1

# TypeScript: build check
cd dashboard && pnpm run build
```

All ruff errors must be zero. Dashboard must produce 0 TypeScript errors.

---

## Step 7 — Verify Full Suite

```bash
# All tests must pass (same set as baseline)
cd engine && .venv/Scripts/python -m pytest tests/ -v

# Diff against baseline
diff /tmp/before_refactor.txt <(cd engine && .venv/Scripts/python -m pytest tests/ -v 2>&1)

# Safety layer must pass
cd engine && .venv/Scripts/python -m pytest tests/test_safety_layer.py -v

# Secrets check
bash scripts/hooks/check-secrets.sh
```

---

## Step 8 — Commit

```
refactor: <short description of what was restructured>
```

Good commit bodies for refactors describe WHY, not what:
- "Split portfolio_router.py because it exceeded 600 lines — extracted service layer"
- "Renamed `get_signal` to `compute_stc_signal` for clarity"

---

## What NOT to Do During a Refactor

- Do NOT change `INSTRUMENT_PARAMS` in `signals.py` (signal behavior change)
- Do NOT alter the safety check order in `safety_layer.py`
- Do NOT change Pydantic response model field names (breaks dashboard contracts)
- Do NOT rename router path strings (breaks all client calls)
- Do NOT remove `inject_dependencies()` calls in `main.py`
- Do NOT add `"use client"` to Server Components unless there is a specific browser API need

---

## Deliverable

```
scope:         <what was refactored>
behavior:      unchanged — all N tests still pass
files changed: <list>
new structure: <how it looks now>
regression check: before/after test comparison attached
```
