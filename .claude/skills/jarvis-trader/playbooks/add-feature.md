# Playbook: Add Feature

Use for: new endpoints, new agents, new market modules, new dashboard pages, new learning behaviors.

---

## External Tools for Feature Work

Before starting, identify which external tools this feature needs:

| Situation | Tool |
|---|---|
| Feature requires live market data research | Claude in Chrome + `TOOLS.md` Cat. 1 |
| Feature requires system design decision | `engineering:system-design` skill |
| Feature needs a formal spec / PRD | `product-management:feature-spec` skill (write-spec) |
| Feature adds a new data analysis capability | `data:data-context-extractor` skill to model schema |
| Review before merging any safety-critical code | `engineering:code-review` + gstack `/review` (both required) |
| QA the new dashboard page when built | gstack `/qa` at `http://localhost:3010` |
| Ship the feature when complete | gstack `/ship` + `playbooks/release.md` |
| Store the spec or design doc | `mcp__c1fc4002-5f49-5f9d-a4e5-93c4ef5d6a75__google_drive_fetch` → save to Drive |

---

## Step 1 — Understand the Request

Before designing anything, answer these questions:

1. What user behavior does this enable?
2. Which layer does it primarily live in? (engine, dashboard, or both)
3. Does it touch the safety layer? (If yes → Tier 3 gate)
4. Does it touch `signals.py INSTRUMENT_PARAMS`? (If yes → walk-forward validation required)
5. Does it require a new LLM agent? (Follow agent contract in `engine/agents/pipeline.py` docstring)
6. Is there an existing router or module it should extend, or does it need a new file?

---

## Step 2 — Design (Before Writing Code)

Sketch the design in a comment or docs block before implementation:

**For a new engine endpoint:**
```
Router:   engine/routers/<area>_router.py (extend existing) OR new file
Path:     GET /new-path  or  POST /new-path
Auth:     X-API-Key required (all endpoints)
Input:    Pydantic request model (define in router or schemas.py)
Output:   Pydantic response model
Service:  which engine module provides the data
Side effects: DB write? LLM call? Market data fetch?
```

**For a new dashboard page:**
```
Route:    dashboard/app/<name>/page.tsx
Type:     Server Component (default) or "use client" if browser APIs needed
Data:     fetchEngine("/new-path") or postEngine("/new-path", body)
Add to:   dashboard/lib/api.ts — new typed function
```

**For a new agent:**
```
File:     engine/agents/<name>.py
Contract: async def analyze(symbol) -> <TypedResult>  (analysts)
          OR matching method for debate/decision/risk stages
Degrade:  must work when LLM key is absent (return neutral result)
Register: add to agents dict in engine/main.py
```

---

## Step 3 — Write Tests First (TDD)

```bash
# Create the test file
# engine/tests/test_<feature_name>.py

# Write the test cases before implementation
# Cover: happy path, error path, edge cases
# Safety-related code: mandatory test, no exceptions
```

---

## Step 4 — Implement

**Python rules:**
- Async with graceful fallback
- Pydantic v2: `model_config = ConfigDict(...)`, `model_validate()`
- Every endpoint: `try/except` → `HTTPException`
- `logging.getLogger(__name__)` — never `print()`
- File ≤ 400 lines (target), ≤ 800 lines (hard max)
- Functions ≤ 50 lines

**TypeScript rules:**
- Default to Server Components; add `"use client"` only for browser APIs
- All engine calls via `fetchEngine` / `postEngine` — NEVER hardcode `localhost:8010`
- Define response interfaces in `dashboard/lib/api.ts`
- Tailwind only — no inline styles

**New router checklist:**
- [ ] `router = APIRouter()` with `prefix=` and `tags=`
- [ ] `inject_dependencies()` function for main.py wiring
- [ ] `app.include_router()` call added to `engine/main.py`
- [ ] `X-API-Key` auth applied (via `APIKeyMiddleware` — automatic for all routes)

---

## Step 5 — Wire Up

**New engine router:**
```python
# engine/main.py — add in the correct section:
from routers.new_router import router as new_router
from routers.new_router import inject_dependencies as inject_new_deps
app.include_router(new_router)
inject_new_deps(...)  # in startup lifespan
```

**New dashboard page:**
```typescript
// dashboard/lib/api.ts — add typed fetch function
export async function fetchNewFeature(): Promise<NewFeatureResponse> {
  return fetchEngine<NewFeatureResponse>("/new-path");
}
```

---

## Step 6 — Verify

```bash
# Run all tests
cd engine && .venv/Scripts/python -m pytest tests/ -v

# Safety layer must still pass
cd engine && .venv/Scripts/python -m pytest tests/test_safety_layer.py -v

# All 24 routers must still be wired
cd engine && .venv/Scripts/python -m pytest tests/test_routes_wired.py -v

# Dashboard must build with 0 TS errors
cd dashboard && pnpm run build

# Secrets check
bash scripts/hooks/check-secrets.sh
```

---

## Step 7 — Commit

```
feat: <short description of what was added>
```

Include in the commit body:
- What the feature does
- Which tests cover it
- Any follow-up work needed

---

## Deliverable

```
feature:     <name and what it does>
files changed: <list of modified files>
tests added: <test file and cases>
wiring:      <how it connects to the rest of the system>
follow-up:   <what's not yet done>
```
