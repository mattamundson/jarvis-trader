# Trade Approval UI — Master Task List
**P0 Blocker | Est. Total: 4–6 hrs | Start: immediately**
**All tasks in strict dependency order. Do not skip ahead.**

Legend: `[ ]` not started · `[~]` in progress · `[x]` done

---

## PHASE 1 — BACKEND ENGINE
*Estimated: 2.5 hrs*

---

### TASK 1.1 — Create package directory
**File ops only. No logic yet.**

- [ ] 1.1.1 — Open terminal in `engine/` directory
- [ ] 1.1.2 — Create directory: `engine/approval/`
- [ ] 1.1.3 — Create file: `engine/approval/__init__.py` (empty file, 0 bytes)
- [ ] 1.1.4 — Verify directory exists: `ls engine/approval/` should show `__init__.py`

---

### TASK 1.2 — Create `engine/approval/store.py`
**The SQLite-backed approval store. Most critical backend file.**

#### 1.2.A — File header and imports

- [ ] 1.2.1 — Create file: `engine/approval/store.py`
- [ ] 1.2.2 — Add module docstring (3 lines: purpose, design decisions, TTL note)
- [ ] 1.2.3 — Add import: `asyncio`
- [ ] 1.2.4 — Add import: `logging`
- [ ] 1.2.5 — Add import: `sqlite3`
- [ ] 1.2.6 — Add import: `uuid`
- [ ] 1.2.7 — Add import: `datetime, timezone` from `datetime`
- [ ] 1.2.8 — Add import: `Optional` from `typing`
- [ ] 1.2.9 — Add import: `Path` from `pathlib`
- [ ] 1.2.10 — Define module-level constant: `APPROVAL_TTL_SECONDS = 4 * 60 * 60`
- [ ] 1.2.11 — Define module-level constant: `DB_PATH = Path("data/jarvis_trader.db")`
- [ ] 1.2.12 — Add: `logger = logging.getLogger(__name__)`

#### 1.2.B — ApprovalStore class skeleton

- [ ] 1.2.13 — Define `class ApprovalStore:` with docstring
- [ ] 1.2.14 — Add class-level type annotation: `_lock: asyncio.Lock`
- [ ] 1.2.15 — Write `__init__(self, db_path: Path = DB_PATH)` — stores `self._db_path`, creates `self._lock = asyncio.Lock()`, calls `self._init_table()`

#### 1.2.C — Schema / `_init_table` method

- [ ] 1.2.16 — Write `_init_table(self) -> None:`
- [ ] 1.2.17 — Open SQLite connection with context manager: `with sqlite3.connect(self._db_path) as conn:`
- [ ] 1.2.18 — Add `CREATE TABLE IF NOT EXISTS trade_approvals` with columns:
  - [ ] 1.2.18a — `approval_id TEXT PRIMARY KEY`
  - [ ] 1.2.18b — `symbol TEXT NOT NULL`
  - [ ] 1.2.18c — `action TEXT NOT NULL` (comment: `-- buy | sell`)
  - [ ] 1.2.18d — `quantity INTEGER NOT NULL`
  - [ ] 1.2.18e — `confidence REAL`
  - [ ] 1.2.18f — `rationale TEXT`
  - [ ] 1.2.18g — `regime TEXT`
  - [ ] 1.2.18h — `stc_value REAL`
  - [ ] 1.2.18i — `pipeline_result TEXT` (comment: `-- full JSON blob`)
  - [ ] 1.2.18j — `status TEXT NOT NULL DEFAULT 'pending'`
  - [ ] 1.2.18k — `created_at TEXT NOT NULL`
  - [ ] 1.2.18l — `decided_at TEXT`
  - [ ] 1.2.18m — `decision_note TEXT`
- [ ] 1.2.19 — Call `conn.commit()`
- [ ] 1.2.20 — Add logger.info confirming initialisation with db_path

#### 1.2.D — `create` method (write path)

- [ ] 1.2.21 — Write `async def create(self, symbol, action, quantity, pipeline_result) -> str:`
- [ ] 1.2.22 — Add `import json` inside method (lazy import)
- [ ] 1.2.23 — Generate UUID: `approval_id = str(uuid.uuid4())`
- [ ] 1.2.24 — Extract `trade = pipeline_result.get("trade_decision", {})`
- [ ] 1.2.25 — Extract `tech = pipeline_result.get("analyst_reports", {}).get("technical", {})`
- [ ] 1.2.26 — Acquire lock: `async with self._lock:`
- [ ] 1.2.27 — Open SQLite connection inside lock
- [ ] 1.2.28 — Write parameterised INSERT with all 11 columns (use `?` placeholders — never f-strings)
- [ ] 1.2.29 — Pass tuple of values: approval_id, symbol, action, quantity, confidence, rationale, regime, stc_value, `json.dumps(pipeline_result)`, `'pending'`, UTC ISO timestamp
- [ ] 1.2.30 — Call `conn.commit()`
- [ ] 1.2.31 — Add `logger.info` logging first 8 chars of approval_id + action + symbol + quantity
- [ ] 1.2.32 — Return `approval_id`

#### 1.2.E — `decide` method (write path)

- [ ] 1.2.33 — Write `async def decide(self, approval_id: str, status: str, note: Optional[str] = None) -> bool:`
- [ ] 1.2.34 — Add docstring: "Returns False if approval not found or not pending"
- [ ] 1.2.35 — Acquire lock: `async with self._lock:`
- [ ] 1.2.36 — Open SQLite connection inside lock
- [ ] 1.2.37 — SELECT current `status` WHERE `approval_id = ?` — fetchone
- [ ] 1.2.38 — Guard: if `not row:` → log warning → `return False`
- [ ] 1.2.39 — Guard: if `row[0] != "pending":` → log warning with current status → `return False`
- [ ] 1.2.40 — Execute UPDATE: set `status=?`, `decided_at=?`, `decision_note=?` WHERE `approval_id=?`
- [ ] 1.2.41 — Call `conn.commit()`
- [ ] 1.2.42 — Add `logger.info` logging approval_id[:8] and new status
- [ ] 1.2.43 — Return `True`

#### 1.2.F — `get_pending` method (read path)

- [ ] 1.2.44 — Write `async def get_pending(self) -> list[dict]:`
- [ ] 1.2.45 — Add `import json` (or ensure already imported at top of method)
- [ ] 1.2.46 — Calculate cutoff timestamp: `datetime.now(UTC) - timedelta(seconds=APPROVAL_TTL_SECONDS)`
- [ ] 1.2.47 — Set `conn.row_factory = sqlite3.Row` so rows behave like dicts
- [ ] 1.2.48 — Execute SELECT `*` WHERE `status = 'pending' AND created_at > ?` ORDER BY `created_at DESC`
- [ ] 1.2.49 — Return `[dict(r) for r in rows]`

#### 1.2.G — `get_history` method (read path)

- [ ] 1.2.50 — Write `async def get_history(self, limit: int = 50) -> list[dict]:`
- [ ] 1.2.51 — Set `conn.row_factory = sqlite3.Row`
- [ ] 1.2.52 — SELECT specific columns only (NOT `pipeline_result` — it's heavy): approval_id, symbol, action, quantity, confidence, regime, status, created_at, decided_at, decision_note
- [ ] 1.2.53 — ORDER BY `created_at DESC` LIMIT `?`
- [ ] 1.2.54 — Return `[dict(r) for r in rows]`

#### 1.2.H — `get_one` method (read path)

- [ ] 1.2.55 — Write `async def get_one(self, approval_id: str) -> Optional[dict]:`
- [ ] 1.2.56 — Set `conn.row_factory = sqlite3.Row`
- [ ] 1.2.57 — SELECT `*` WHERE `approval_id = ?` — fetchone
- [ ] 1.2.58 — Guard: if `not row:` → `return None`
- [ ] 1.2.59 — Deserialise `pipeline_result` field: `json.loads(result["pipeline_result"])` — only if field is not None
- [ ] 1.2.60 — Return `dict(row)` with deserialised pipeline_result

#### 1.2.I — Module-level singleton

- [ ] 1.2.61 — Below the class, add: `_approval_store: Optional[ApprovalStore] = None`
- [ ] 1.2.62 — Write `def get_approval_store() -> ApprovalStore:`
- [ ] 1.2.63 — Implement lazy init pattern: `global _approval_store; if _approval_store is None: _approval_store = ApprovalStore()`
- [ ] 1.2.64 — Return `_approval_store`

#### 1.2.J — Final verification of store.py

- [ ] 1.2.65 — Count lines: target ~130. If much larger, check for accidental duplication
- [ ] 1.2.66 — Check: no bare `except:` clauses — use specific exception types
- [ ] 1.2.67 — Check: no f-strings used in SQL — only `?` placeholders
- [ ] 1.2.68 — Check: all SQL connections use context managers (`with sqlite3.connect(...) as conn:`)
- [ ] 1.2.69 — Check: `asyncio.Lock` acquired before every write operation
- [ ] 1.2.70 — Run quick syntax check: `cd engine && .venv/Scripts/python -c "from approval.store import get_approval_store; print('OK')"`

---

### TASK 1.3 — Create `engine/approval/models.py`
**Pydantic v2 response models for the API surface.**

- [ ] 1.3.1 — Create file: `engine/approval/models.py`
- [ ] 1.3.2 — Add module docstring: "Pydantic v2 models for the approval API surface"
- [ ] 1.3.3 — Import: `from datetime import datetime`
- [ ] 1.3.4 — Import: `from typing import Optional`
- [ ] 1.3.5 — Import: `from pydantic import BaseModel, Field`

#### 1.3.A — `PendingApproval` model

- [ ] 1.3.6 — Define `class PendingApproval(BaseModel):`
- [ ] 1.3.7 — Add field: `approval_id: str`
- [ ] 1.3.8 — Add field: `symbol: str`
- [ ] 1.3.9 — Add field: `action: str` (comment: `# "buy" | "sell"`)
- [ ] 1.3.10 — Add field: `quantity: int`
- [ ] 1.3.11 — Add field: `confidence: Optional[float]`
- [ ] 1.3.12 — Add field: `rationale: Optional[str]`
- [ ] 1.3.13 — Add field: `regime: Optional[str]`
- [ ] 1.3.14 — Add field: `stc_value: Optional[float]`
- [ ] 1.3.15 — Add field: `status: str` (comment: `# always "pending"`)
- [ ] 1.3.16 — Add field: `created_at: str`
- [ ] 1.3.17 — Add field: `age_seconds: Optional[float] = None`

#### 1.3.B — `ApprovalHistoryItem` model

- [ ] 1.3.18 — Define `class ApprovalHistoryItem(BaseModel):`
- [ ] 1.3.19 — Add fields: `approval_id, symbol, action, quantity` (all non-optional)
- [ ] 1.3.20 — Add fields: `confidence: Optional[float]`, `regime: Optional[str]`
- [ ] 1.3.21 — Add field: `status: str` (comment: `# pending|approved|rejected|expired`)
- [ ] 1.3.22 — Add fields: `created_at: str`, `decided_at: Optional[str]`, `decision_note: Optional[str]`

#### 1.3.C — `ApprovalDecisionRequest` model

- [ ] 1.3.23 — Define `class ApprovalDecisionRequest(BaseModel):`
- [ ] 1.3.24 — Add field: `note: Optional[str] = Field(None, description="Optional reason for this decision")`

#### 1.3.D — `ApprovalDetailResponse` model

- [ ] 1.3.25 — Define `class ApprovalDetailResponse(BaseModel):`
- [ ] 1.3.26 — Add all fields from `PendingApproval` PLUS:
- [ ] 1.3.27 — Add field: `pipeline_result: Optional[dict]` (the heavy JSON blob)
- [ ] 1.3.28 — Add fields: `decided_at: Optional[str]`, `decision_note: Optional[str]`

#### 1.3.E — Verification

- [ ] 1.3.29 — Count lines: target ~55. If larger, check for typos
- [ ] 1.3.30 — Syntax check: `cd engine && .venv/Scripts/python -c "from approval.models import PendingApproval; print('OK')"`

---

### TASK 1.4 — Create `engine/routers/approval_router.py`
**Five HTTP endpoints. Depends on Task 1.2 and 1.3.**

#### 1.4.A — File header

- [ ] 1.4.1 — Create file: `engine/routers/approval_router.py`
- [ ] 1.4.2 — Add module docstring listing all 5 endpoints with method + path
- [ ] 1.4.3 — Import: `logging`, `datetime`, `timezone` from `datetime`
- [ ] 1.4.4 — Import: `APIRouter`, `HTTPException` from `fastapi`
- [ ] 1.4.5 — Import all 4 models from `approval.models`
- [ ] 1.4.6 — Import `get_approval_store` from `approval.store`
- [ ] 1.4.7 — Add: `logger = logging.getLogger(__name__)`
- [ ] 1.4.8 — Create router: `router = APIRouter(prefix="/pipeline", tags=["approvals"])`

#### 1.4.B — `GET /pipeline/pending-approvals`

- [ ] 1.4.9 — Add decorator: `@router.get("/pending", response_model=list[PendingApproval])`
- [ ] 1.4.10 — Write `async def list_pending_approvals():`
- [ ] 1.4.11 — Add docstring: "Return all non-expired pending trade approvals"
- [ ] 1.4.12 — Call `store = get_approval_store()`
- [ ] 1.4.13 — Call `rows = await store.get_pending()`
- [ ] 1.4.14 — Compute `now = datetime.now(timezone.utc)`
- [ ] 1.4.15 — Loop through rows, compute `age_seconds` for each: `(now - datetime.fromisoformat(r["created_at"])).total_seconds()`
- [ ] 1.4.16 — Build and return `list[PendingApproval]` with `age_seconds` populated

#### 1.4.C — `GET /pipeline/pending-approvals/{approval_id}`

- [ ] 1.4.17 — Add decorator: `@router.get("/pending/{approval_id}", response_model=ApprovalDetailResponse)`
- [ ] 1.4.18 — Write `async def get_pending_approval(approval_id: str):`
- [ ] 1.4.19 — Add docstring: "Full detail for single pending approval, includes pipeline result"
- [ ] 1.4.20 — Call `store.get_one(approval_id)`
- [ ] 1.4.21 — Guard: `if not record:` → raise `HTTPException(404, detail=f"Approval {approval_id} not found")`
- [ ] 1.4.22 — Guard: `if record["status"] != "pending":` → raise `HTTPException(409, detail=f"Approval {approval_id} is already {record['status']}")`
- [ ] 1.4.23 — Return `ApprovalDetailResponse(**record)`

#### 1.4.D — `POST /pipeline/pending-approvals/{approval_id}/approve`

- [ ] 1.4.24 — Add decorator: `@router.post("/{approval_id}/approve")`
- [ ] 1.4.25 — Write `async def approve_trade(approval_id: str, body: ApprovalDecisionRequest = ApprovalDecisionRequest()):`
- [ ] 1.4.26 — Add docstring explaining what happens (records approval, execution wiring is Sprint 12)
- [ ] 1.4.27 — Call `ok = await store.decide(approval_id, "approved", note=body.note)`
- [ ] 1.4.28 — Guard: `if not ok:` → raise `HTTPException(404, detail=...)`
- [ ] 1.4.29 — Add `# TODO Sprint 12: trigger IB order submission here` comment (critical — don't skip this)
- [ ] 1.4.30 — Add `logger.info("Trade APPROVED by human: %s (note: %s)", approval_id[:8], body.note)`
- [ ] 1.4.31 — Return dict: `{ "approval_id", "status": "approved", "decided_at": UTC ISO, "message": "..." }`

#### 1.4.E — `POST /pipeline/pending-approvals/{approval_id}/reject`

- [ ] 1.4.32 — Add decorator: `@router.post("/{approval_id}/reject")`
- [ ] 1.4.33 — Write `async def reject_trade(approval_id: str, body: ApprovalDecisionRequest = ApprovalDecisionRequest()):`
- [ ] 1.4.34 — Call `ok = await store.decide(approval_id, "rejected", note=body.note)`
- [ ] 1.4.35 — Guard: `if not ok:` → raise `HTTPException(404, ...)`
- [ ] 1.4.36 — Add `logger.info("Trade REJECTED by human: %s", approval_id[:8])`
- [ ] 1.4.37 — Return dict: `{ "approval_id", "status": "rejected", "decided_at": UTC ISO, "message": "..." }`

#### 1.4.F — `GET /pipeline/pending-approvals/history`

- [ ] 1.4.38 — Add decorator: `@router.get("/history", response_model=list[ApprovalHistoryItem])`
- [ ] 1.4.39 — Write `async def get_approval_history(limit: int = 50):`
- [ ] 1.4.40 — Call `rows = await store.get_history(limit=limit)`
- [ ] 1.4.41 — Return `[ApprovalHistoryItem(**r) for r in rows]`

#### 1.4.G — Verification

- [ ] 1.4.42 — Count lines: target ~105. If larger, recheck for unintentional duplication
- [ ] 1.4.43 — Verify all 5 endpoints have correct HTTP verb (2× GET pending, 1× GET history, 1× POST approve, 1× POST reject)
- [ ] 1.4.44 — Verify `prefix="/pipeline"` is on the router (NOT on individual decorators)
- [ ] 1.4.45 — Syntax check: `cd engine && .venv/Scripts/python -c "from routers.approvals_router import router; print(len(router.routes), 'routes')"`
  - Expected output: `5 routes`

---

### TASK 1.5 — Wire router into `engine/main.py`
**Two lines only. High risk of CRLF truncation — use Edit tool, not Write.**

- [ ] 1.5.1 — Open `engine/main.py` with Read tool — note the line number of the last `from routers.X import router as X_router` import
- [ ] 1.5.2 — Find the alphabetical position for `approvals_router` among the existing router imports
- [ ] 1.5.3 — Use Edit tool to insert: `from routers.approvals_router import router as approvals_router`
  - Insert BETWEEN two existing router imports to keep alphabetical order
  - Do NOT use Write tool — main.py is 4,605 lines, Write would risk truncation
- [ ] 1.5.4 — Find the `app.include_router(...)` block — note the line number
- [ ] 1.5.5 — Use Edit tool to insert: `app.include_router(approvals_router)` in the include block
  - Again, Edit tool only
- [ ] 1.5.6 — Verify Edit took by reading back the two changed lines with Read tool (line numbers ±2)
- [ ] 1.5.7 — Count total `include_router` calls before and after — should be exactly +1

---

### TASK 1.6 — Patch `engine/routers/pipeline_router.py`
**Gate the auto-log on `requires_human`. Most complex edit.**

#### 1.6.A — Locate the auto-log block

- [ ] 1.6.1 — Read `engine/routers/pipeline_router.py` — identify lines ~295–355
- [ ] 1.6.2 — Find the exact condition that triggers paper trade logging (likely `if final_action in ("buy", "sell", ...)` or similar)
- [ ] 1.6.3 — Note the exact line number of that condition
- [ ] 1.6.4 — Read 20 lines above and 20 lines below to understand full context before editing
- [ ] 1.6.5 — Identify where `result` dict is assembled — confirm `requires_human` key is present

#### 1.6.B — Add approval import (lazy, inside function scope)

- [ ] 1.6.6 — Inside the route handler function (NOT at module top level), add lazy import:
  ```python
  from approval.store import get_approval_store
  ```
  Place this immediately before the block you're about to modify

#### 1.6.C — Split the auto-log condition

- [ ] 1.6.7 — Extract `requires_human` from result dict:
  ```python
  requires_human = result.get("requires_human", True)  # default True = safe
  ```
- [ ] 1.6.8 — Wrap existing auto-log code in: `if final_action in (...) and not requires_human:`
  - Indent the entire existing auto-log block by 4 spaces (use Edit tool carefully)
- [ ] 1.6.9 — Add `elif final_action in (...) and requires_human:` branch immediately after the existing block
- [ ] 1.6.10 — Inside the elif branch, add approval creation:
  ```python
  store = get_approval_store()
  approval_id = await store.create(
      symbol=symbol,
      action=final_action,
      quantity=result.get("final_quantity", 1),
      pipeline_result=result,
  )
  result["approval_id"] = approval_id
  result["approval_status"] = "pending"
  logger.info("Trade pending human approval: %s → approval_id=%s", symbol, approval_id[:8])
  ```

#### 1.6.D — Patch the return value

- [ ] 1.6.11 — Find the `return {...}` at the end of the route handler
- [ ] 1.6.12 — Add to the return dict: `"approval_id": result.get("approval_id")`
- [ ] 1.6.13 — Add to the return dict: `"approval_status": result.get("approval_status")`
- [ ] 1.6.14 — Add to the return dict: `"requires_human": requires_human` (if not already there)

#### 1.6.E — Verification

- [ ] 1.6.15 — Read back the patched section with Read tool — confirm indentation is correct
- [ ] 1.6.16 — Count opening/closing brackets in the patched region — must be balanced
- [ ] 1.6.17 — Confirm `requires_human = True` (default) means trades are stored for approval, not auto-executed
- [ ] 1.6.18 — Confirm `requires_human = False` path still runs the original auto-log code unchanged
- [ ] 1.6.19 — Syntax check: `cd engine && .venv/Scripts/python -c "from routers.pipeline_router import router; print('OK')"`

---

### TASK 1.7 — Engine smoke test (backend complete checkpoint)
**Do not start Phase 2 until all of these pass.**

- [ ] 1.7.1 — Run: `.\restart_engine.ps1` — watch for startup errors
- [ ] 1.7.2 — Confirm health check passes: `curl http://localhost:8010/health` → `{"status": "healthy"}`
- [ ] 1.7.3 — Check Swagger docs include new endpoints: open `http://localhost:8010/docs` → find `/approvals` section → should show all 5 endpoints
- [ ] 1.7.4 — Test empty pending: `curl -H "X-API-Key: YOUR_KEY" http://localhost:8010/pipeline/pending-approvals` → `[]`
- [ ] 1.7.5 — Test empty history: `curl -H "X-API-Key: YOUR_KEY" http://localhost:8010/pipeline/pending-approvals/history` → `[]`
- [ ] 1.7.6 — Test 404 on approve nonexistent: `curl -X POST -H "X-API-Key: YOUR_KEY" http://localhost:8010/approvals/fake-id/approve -d '{}'` → `{"detail": "Approval fake-id not found..."}`
- [ ] 1.7.7 — Test 404 on reject nonexistent — same as above but `/reject`
- [ ] 1.7.8 — Trigger a pipeline run: `curl -X POST -H "X-API-Key: YOUR_KEY" http://localhost:8010/pipeline/run -d '{"symbol":"MCL","is_futures":true}'`
- [ ] 1.7.9 — If pipeline produces a BUY/SELL signal: `curl .../pipeline/pending-approvals` → should now show the pending card
- [ ] 1.7.10 — Approve it: `curl -X POST .../pipeline/pending-approvals/{id}/approve -d '{"note":"smoke test"}'` → `{"status":"approved"}`
- [ ] 1.7.11 — Confirm pending is empty again: `curl .../pipeline/pending-approvals` → `[]`
- [ ] 1.7.12 — Confirm history shows approved entry: `curl .../pipeline/pending-approvals/history` → one entry with `status: approved`
- [ ] 1.7.13 — Check engine log for `logger.info` messages — confirm no errors
- [ ] 1.7.14 — Check `data/jarvis_trader.db` exists and has `trade_approvals` table: `sqlite3 data/jarvis_trader.db ".tables"`

**✅ Backend complete. Proceed to Phase 2.**

---

## PHASE 2 — FRONTEND DASHBOARD
*Estimated: 1.5 hrs*

---

### TASK 2.1 — Add TypeScript types to `dashboard/lib/api.ts`
**Append only. Do NOT modify existing types or functions.**

- [ ] 2.1.1 — Read `dashboard/lib/api.ts` — note the current line count
- [ ] 2.1.2 — Scroll to the last line of the file — identify where to append
- [ ] 2.1.3 — Add section comment: `// ─── Trade Approvals ─────────────────────────────────────────────────────────`

#### 2.1.A — `PendingApproval` interface

- [ ] 2.1.4 — Add `export interface PendingApproval {`
- [ ] 2.1.5 — Add field: `approval_id: string`
- [ ] 2.1.6 — Add field: `symbol: string`
- [ ] 2.1.7 — Add field: `action: "buy" | "sell"` (union literal type — not just `string`)
- [ ] 2.1.8 — Add field: `quantity: number`
- [ ] 2.1.9 — Add field: `confidence: number | null`
- [ ] 2.1.10 — Add field: `rationale: string | null`
- [ ] 2.1.11 — Add field: `regime: string | null`
- [ ] 2.1.12 — Add field: `stc_value: number | null`
- [ ] 2.1.13 — Add field: `status: "pending"`
- [ ] 2.1.14 — Add field: `created_at: string`
- [ ] 2.1.15 — Add field: `age_seconds: number | null`
- [ ] 2.1.16 — Close with `}`

#### 2.1.B — `ApprovalHistoryItem` interface

- [ ] 2.1.17 — Add `export interface ApprovalHistoryItem {`
- [ ] 2.1.18 — Add fields: `approval_id, symbol, action, quantity` (non-nullable)
- [ ] 2.1.19 — Add fields: `confidence: number | null`, `regime: string | null`
- [ ] 2.1.20 — Add field: `status: "pending" | "approved" | "rejected" | "expired"` (union — not string)
- [ ] 2.1.21 — Add fields: `created_at: string`, `decided_at: string | null`, `decision_note: string | null`
- [ ] 2.1.22 — Close with `}`

#### 2.1.C — `ApprovalDecisionResult` interface

- [ ] 2.1.23 — Add `export interface ApprovalDecisionResult {`
- [ ] 2.1.24 — Add field: `approval_id: string`
- [ ] 2.1.25 — Add field: `status: "approved" | "rejected"`
- [ ] 2.1.26 — Add field: `decided_at: string`
- [ ] 2.1.27 — Add field: `message: string`
- [ ] 2.1.28 — Close with `}`

#### 2.1.D — Verification

- [ ] 2.1.29 — Confirm file line count increased by ~35 lines
- [ ] 2.1.30 — Run TypeScript check: `cd dashboard && ./node_modules/.bin/tsc --noEmit`
  - Must show zero new errors. If errors, check for typos in interface definitions.
- [ ] 2.1.31 — Confirm all 3 interfaces are exported (have `export` keyword)

---

### TASK 2.2 — Create `dashboard/components/ApprovalPanel.tsx`
**The main UI component. Largest frontend file.**

#### 2.2.A — File setup

- [ ] 2.2.1 — Create file: `dashboard/components/ApprovalPanel.tsx`
- [ ] 2.2.2 — Add `"use client";` as the very first line (required — uses useState/useSWR)
- [ ] 2.2.3 — Add blank line after directive
- [ ] 2.2.4 — Add JSDoc block: component purpose, polling interval, what it shows

#### 2.2.B — Imports

- [ ] 2.2.5 — Import from React: `{ useState, useCallback }` (NOT useEffect — we use SWR)
- [ ] 2.2.6 — Import `useSWR` from `"swr"`
- [ ] 2.2.7 — Import Lucide icons: `{ CheckCircle, XCircle, Clock, AlertTriangle, TrendingUp, TrendingDown }` from `"lucide-react"`
- [ ] 2.2.8 — Import `{ fetchEngine, postEngine }` from `"@/lib/api"`
- [ ] 2.2.9 — Import `type { PendingApproval, ApprovalHistoryItem, ApprovalDecisionResult }` from `"@/lib/api"`
- [ ] 2.2.10 — Verify: no import of `useEffect` — if you wrote it, remove it

#### 2.2.C — SWR fetcher functions (module level, outside component)

- [ ] 2.2.11 — Write `const fetchPending = (url: string) => fetchEngine<PendingApproval[]>(url).then((r) => r ?? [])`
- [ ] 2.2.12 — Write `const fetchHistory = (url: string) => fetchEngine<ApprovalHistoryItem[]>(url).then((r) => r ?? [])`
- [ ] 2.2.13 — Verify both handle `null` response from fetchEngine (the `?? []` fallback)

#### 2.2.D — Helper functions (module level)

- [ ] 2.2.14 — Write `function ageLabel(seconds: number | null): string`
  - [ ] 2.2.14a — If null → return `"—"`
  - [ ] 2.2.14b — If < 60 → return `"${Math.round(seconds)}s ago"`
  - [ ] 2.2.14c — If < 3600 → return `"${Math.round(seconds / 60)}m ago"`
  - [ ] 2.2.14d — Else → return `"${Math.round(seconds / 3600)}h ago"`
- [ ] 2.2.15 — Write `function confidenceColor(c: number | null): string`
  - [ ] 2.2.15a — If null → `"text-zinc-400"`
  - [ ] 2.2.15b — If >= 0.75 → `"text-emerald-400"` (green — strong signal)
  - [ ] 2.2.15c — If >= 0.55 → `"text-yellow-400"` (yellow — marginal)
  - [ ] 2.2.15d — Else → `"text-red-400"` (red — weak signal)

#### 2.2.E — Component state

- [ ] 2.2.16 — Write: `export default function ApprovalPanel() {`
- [ ] 2.2.17 — Add state: `const [deciding, setDeciding] = useState<Record<string, boolean>>({})`
  - This tracks which approvals have a button click in flight
- [ ] 2.2.18 — Add state: `const [errors, setErrors] = useState<Record<string, string>>({})`
  - Per-approval error messages

#### 2.2.F — SWR hooks

- [ ] 2.2.19 — Add pending SWR hook:
  ```tsx
  const { data: pending = [], mutate: mutatePending } = useSWR(
    "/pipeline/pending-approvals",
    fetchPending,
    { refreshInterval: 5000, revalidateOnFocus: true }
  );
  ```
- [ ] 2.2.20 — Add history SWR hook:
  ```tsx
  const { data: history = [], mutate: mutateHistory } = useSWR(
    "/pipeline/pending-approvals/history?limit=10",
    fetchHistory,
    { refreshInterval: 10000 }
  );
  ```
- [ ] 2.2.21 — Verify: `pending` defaults to `[]` so `.map()` never crashes on null

#### 2.2.G — `decide` callback

- [ ] 2.2.22 — Write `const decide = useCallback(async (approvalId: string, decision: "approve" | "reject") => {`
- [ ] 2.2.23 — Mark approvalId as deciding: `setDeciding(d => ({ ...d, [approvalId]: true }))`
- [ ] 2.2.24 — Clear previous error: `setErrors(e => ({ ...e, [approvalId]: "" }))`
- [ ] 2.2.25 — Wrap in `try/catch/finally`:
  - try: `await postEngine<ApprovalDecisionResult>(\`/approvals/${approvalId}/${decision}\`, {})`
  - try: `await mutatePending()` — refresh pending list
  - try: `await mutateHistory()` — refresh history
  - catch: `const msg = err instanceof Error ? err.message : "Request failed"` → `setErrors(...)`
  - finally: `setDeciding(d => ({ ...d, [approvalId]: false }))`
- [ ] 2.2.26 — Close useCallback with dependency array: `[mutatePending, mutateHistory]`

#### 2.2.H — JSX: outer container

- [ ] 2.2.27 — Open return with `<div className="space-y-4">`

#### 2.2.I — JSX: header row

- [ ] 2.2.28 — Add header `<div>` with flex layout
- [ ] 2.2.29 — Add `<AlertTriangle className="w-4 h-4 text-amber-400" />`
- [ ] 2.2.30 — Add `<span>Pending Approvals</span>` with uppercase tracking-wider styling
- [ ] 2.2.31 — Add conditional badge: `{pending.length > 0 && <span className="bg-amber-500 text-black ...>{pending.length}</span>}`
  - Badge only visible when there are pending items

#### 2.2.J — JSX: empty state

- [ ] 2.2.32 — Add `{pending.length === 0 ? (<div ...>No pending approvals</div>) : (...)}`

#### 2.2.K — JSX: pending cards loop

- [ ] 2.2.33 — Add `{pending.map((appr) => (<div key={appr.approval_id} ...>`)
- [ ] 2.2.34 — Card border: `border border-amber-500/40 bg-amber-950/20 rounded-lg p-4 space-y-3` (amber theme = attention)
- [ ] 2.2.35 — Add top row: symbol + direction icon + action badge + quantity + age
  - [ ] 2.2.35a — `{appr.action === "buy" ? <TrendingUp .../> : <TrendingDown .../>}`
  - [ ] 2.2.35b — `<span>{appr.symbol}</span>` bold, large
  - [ ] 2.2.35c — Action badge: green bg for buy, red bg for sell
  - [ ] 2.2.35d — `× {appr.quantity}` in zinc-400
  - [ ] 2.2.35e — Age in top-right corner: `<Clock className="w-3 h-3" /> {ageLabel(appr.age_seconds)}`
- [ ] 2.2.36 — Add signal details grid (3 columns):
  - [ ] 2.2.36a — Col 1: "Confidence" label + `{confidenceColor(appr.confidence)}` styled value
  - [ ] 2.2.36b — Col 2: "Regime" label + `{appr.regime ?? "—"}`
  - [ ] 2.2.36c — Col 3: "STC" label + `{appr.stc_value?.toFixed(1) ?? "—"}`
- [ ] 2.2.37 — Add rationale text (conditional, truncated at 280 chars):
  - `{appr.rationale && <p ...>{appr.rationale.slice(0, 280)}{appr.rationale.length > 280 ? "…" : ""}</p>}`
- [ ] 2.2.38 — Add error message (conditional): `{errors[appr.approval_id] && <p className="text-xs text-red-400">...</p>}`
- [ ] 2.2.39 — Add action buttons row:
  - [ ] 2.2.39a — Approve button: `onClick={() => decide(appr.approval_id, "approve")}` | `disabled={deciding[appr.approval_id]}` | emerald background
  - [ ] 2.2.39b — Inside Approve: `<CheckCircle className="w-4 h-4" />` + `{deciding[appr.approval_id] ? "…" : "Approve"}`
  - [ ] 2.2.39c — Reject button: `onClick={() => decide(appr.approval_id, "reject")}` | same disabled logic | red background
  - [ ] 2.2.39d — Inside Reject: `<XCircle className="w-4 h-4" />` + `{deciding[appr.approval_id] ? "…" : "Reject"}`
  - [ ] 2.2.39e — Both buttons: `disabled:opacity-50 disabled:cursor-not-allowed` Tailwind classes
- [ ] 2.2.40 — Close card div, close map, close ternary

#### 2.2.L — JSX: history section

- [ ] 2.2.41 — Add `{history.length > 0 && (<div ...>` conditional block
- [ ] 2.2.42 — Add "Recent Decisions" heading in zinc-500
- [ ] 2.2.43 — Map history items: `{history.map((h) => (<div key={h.approval_id} ...>`)
- [ ] 2.2.44 — Left side of each row: status icon + symbol + action + quantity
  - `approved` → `<CheckCircle className="text-emerald-400" />`
  - `rejected` → `<XCircle className="text-red-400" />`
  - other → `<Clock className="text-zinc-500" />`
- [ ] 2.2.45 — Right side: status text (colored) + decided_at time
- [ ] 2.2.46 — Close all divs, close component function

#### 2.2.M — Final verification of ApprovalPanel.tsx

- [ ] 2.2.47 — Count lines: target ~175. If significantly over, check for duplicated blocks
- [ ] 2.2.48 — Check: `"use client"` is the first line (no blank line above it, no imports above it)
- [ ] 2.2.49 — Check: no `useEffect` anywhere in the file
- [ ] 2.2.50 — Check: `default export` is present at the function definition
- [ ] 2.2.51 — Check: both `fetchEngine` and `postEngine` are used (not hardcoded fetch calls)
- [ ] 2.2.52 — Check: no hardcoded `http://localhost:8010` anywhere in the file
- [ ] 2.2.53 — Check: `deciding[appr.approval_id]` guards both buttons (not just one)
- [ ] 2.2.54 — Run TS check: `cd dashboard && ./node_modules/.bin/tsc --noEmit` — zero new errors

---

### TASK 2.3 — Mount on `dashboard/app/command-center/page.tsx`
**Two insertions: import + JSX mount. Use Edit tool only.**

#### 2.3.A — Add the import

- [ ] 2.3.1 — Read first 50 lines of `dashboard/app/command-center/page.tsx` to find import block
- [ ] 2.3.2 — Find the last component import line (e.g. `import SomeWidget from "@/components/..."`)
- [ ] 2.3.3 — Use Edit tool to insert after last component import:
  ```tsx
  import ApprovalPanel from "@/components/ApprovalPanel";
  ```
- [ ] 2.3.4 — Read back those lines to confirm import was inserted correctly

#### 2.3.B — Add the JSX

- [ ] 2.3.5 — Read enough of the JSX to understand the grid/column layout (typically a 2-col grid)
- [ ] 2.3.6 — Identify the ideal position: **above the fold, in a prominent position** — recommendation: first card in left or main column, before positions/P&L panels
- [ ] 2.3.7 — Use Edit tool to insert the approval card:
  ```tsx
  {/* Trade Approvals — REQUIRE_HUMAN_APPROVAL gate */}
  <Card className="border-amber-500/30 bg-zinc-900/50">
    <CardHeader className="pb-2">
      <CardTitle className="text-sm font-semibold text-zinc-200">
        Trade Approvals
      </CardTitle>
    </CardHeader>
    <CardContent>
      <ApprovalPanel />
    </CardContent>
  </Card>
  ```
- [ ] 2.3.8 — Read back the inserted block to verify indentation matches surrounding code
- [ ] 2.3.9 — Verify `Card`, `CardHeader`, `CardTitle`, `CardContent` are all already imported at top of the file
  - If any are missing, add them to the existing `@/components/ui/card` import line

#### 2.3.C — Build verification

- [ ] 2.3.10 — Run: `cd dashboard && ./node_modules/.bin/tsc --noEmit` — must be 0 errors
- [ ] 2.3.11 — Run: `cd dashboard && pnpm run build` — must complete with 0 TypeScript errors, all routes generated
- [ ] 2.3.12 — If build fails: read error message carefully — most likely cause is a missing import or prop type mismatch
- [ ] 2.3.13 — Confirm build output shows `command-center` route was generated (it should appear in the route list)

---

## PHASE 3 — TESTS
*Estimated: 1 hr*

---

### TASK 3.1 — Create `engine/tests/test_approvals.py`

#### 3.1.A — File setup

- [ ] 3.1.1 — Create file: `engine/tests/test_approvals.py`
- [ ] 3.1.2 — Add module docstring: "Tests for the trade approval store and API endpoints"
- [ ] 3.1.3 — Import: `asyncio`, `pytest`
- [ ] 3.1.4 — Import: `Path` from `pathlib`
- [ ] 3.1.5 — Import: `ApprovalStore` from `approval.store`

#### 3.1.B — Test fixture

- [ ] 3.1.6 — Write `@pytest.fixture` named `store` that accepts `tmp_path`
- [ ] 3.1.7 — Returns `ApprovalStore(db_path=tmp_path / "test.db")` — isolated DB per test

#### 3.1.C — Store unit tests

- [ ] 3.1.8 — Write `@pytest.mark.asyncio async def test_create_and_get_pending(store):`
  - [ ] 3.1.8a — Create one approval
  - [ ] 3.1.8b — Assert approval_id is truthy
  - [ ] 3.1.8c — Call get_pending() → assert length == 1
  - [ ] 3.1.8d — Assert symbol matches
  - [ ] 3.1.8e — Assert status == "pending"

- [ ] 3.1.9 — Write `async def test_approve(store):`
  - [ ] 3.1.9a — Create approval
  - [ ] 3.1.9b — Call `decide(id, "approved", note="looks good")`
  - [ ] 3.1.9c — Assert `ok is True`
  - [ ] 3.1.9d — Assert `get_pending()` returns `[]`
  - [ ] 3.1.9e — Assert `get_history()[0]["status"] == "approved"`
  - [ ] 3.1.9f — Assert `get_history()[0]["decision_note"] == "looks good"`

- [ ] 3.1.10 — Write `async def test_reject(store):`
  - [ ] 3.1.10a — Create approval
  - [ ] 3.1.10b — Call `decide(id, "rejected", note="regime unfavourable")`
  - [ ] 3.1.10c — Assert `ok is True`
  - [ ] 3.1.10d — Assert `get_history()[0]["status"] == "rejected"`

- [ ] 3.1.11 — Write `async def test_double_decide_returns_false(store):`
  - [ ] 3.1.11a — Create approval
  - [ ] 3.1.11b — Approve it
  - [ ] 3.1.11c — Try to reject it — assert returns `False`
  - [ ] 3.1.11d — Check history still shows "approved" (not overwritten)

- [ ] 3.1.12 — Write `async def test_nonexistent_id_returns_false(store):`
  - Call `decide("does-not-exist", "approved")` → assert `False`

- [ ] 3.1.13 — Write `async def test_empty_pending_on_fresh_store(store):`
  - `get_pending()` on new store → assert `== []`

- [ ] 3.1.14 — Write `async def test_history_returns_newest_first(store):`
  - [ ] 3.1.14a — Create 3 approvals
  - [ ] 3.1.14b — Decide all 3
  - [ ] 3.1.14c — Assert history[0] is the most recent
  - [ ] 3.1.14d — Assert len(history) == 3

#### 3.1.D — API endpoint tests (using existing test_client fixture)

- [ ] 3.1.15 — Write `def test_pending_endpoint_empty(test_client):`
  - GET `/pipeline/pending-approvals` → 200 → `[]`
- [ ] 3.1.16 — Write `def test_history_endpoint_empty(test_client):`
  - GET `/pipeline/pending-approvals/history` → 200 → `[]`
- [ ] 3.1.17 — Write `def test_approve_nonexistent_returns_404(test_client):`
  - POST `/approvals/fake-id/approve` → 404
- [ ] 3.1.18 — Write `def test_reject_nonexistent_returns_404(test_client):`
  - POST `/approvals/fake-id/reject` → 404

---

### TASK 3.2 — Run the full test suite

- [ ] 3.2.1 — Run: `cd engine && .venv/Scripts/python -m pytest tests/test_approvals.py -v`
  - All new tests should pass
  - If any fail: read error → fix → re-run before proceeding
- [ ] 3.2.2 — Run: `cd engine && .venv/Scripts/python -m pytest tests/test_safety_layer.py -v`
  - **All safety tests must still pass** — if any fail, something in Phase 1 broke them → investigate immediately
- [ ] 3.2.3 — Run: `cd engine && .venv/Scripts/python -m pytest tests/ -v`
  - Note the total: should be previous count + new approval tests
  - No regressions in existing passing tests (count of failures must not increase)
- [ ] 3.2.4 — Run: `cd dashboard && pnpm run build` — 0 TypeScript errors, all routes generated

---

## PHASE 4 — FULL MANUAL SMOKE TEST
*End-to-end verification. Do this with both engine and dashboard running.*

### Setup

- [ ] 4.1 — Start engine: `cd engine && .venv/Scripts/python -m uvicorn main:app --port 8010`
  OR run `.\restart_engine.ps1`
- [ ] 4.2 — Start dashboard: `cd dashboard && pnpm dev`
- [ ] 4.3 — Open browser to `http://localhost:3010/command-center`
- [ ] 4.4 — Verify the "Trade Approvals" card is visible on the command center page
- [ ] 4.5 — Verify the card shows "No pending approvals" text

### Trigger a signal

- [ ] 4.6 — Open a second tab: `http://localhost:8010/docs`
- [ ] 4.7 — Find `POST /pipeline/run` endpoint
- [ ] 4.8 — Execute with body: `{"symbol": "MCL", "is_futures": true}`
- [ ] 4.9 — Note the `final_action` in the response
  - If `"hold"`: repeat with MNQ or wait for a better signal — the approval card won't appear for HOLDs
  - If `"buy"` or `"sell"`: proceed to next step

### Approval flow

- [ ] 4.10 — Within 5 seconds, verify the amber approval card appears on the command center page (SWR poll)
- [ ] 4.11 — Verify the card shows:
  - [ ] 4.11a — Correct symbol (MCL or MNQ)
  - [ ] 4.11b — Correct action (buy or sell) with correct icon (TrendingUp/Down)
  - [ ] 4.11c — Quantity number
  - [ ] 4.11d — Confidence percentage (if available)
  - [ ] 4.11e — Regime label (if available)
  - [ ] 4.11f — STC value (if available)
  - [ ] 4.11g — Rationale text (truncated if long)
  - [ ] 4.11h — Age label (e.g. "3s ago")
- [ ] 4.12 — Click Approve button
  - [ ] 4.12a — Button shows "…" during API call
  - [ ] 4.12b — Card disappears after response
  - [ ] 4.12c — "No pending approvals" text reappears
  - [ ] 4.12d — History section appears with one "APPROVED" entry
- [ ] 4.13 — Trigger another pipeline run
- [ ] 4.14 — Wait for card to appear (if BUY/SELL signal)
- [ ] 4.15 — Click Reject button
  - [ ] 4.15a — Card disappears
  - [ ] 4.15b — History shows "REJECTED" entry
  - [ ] 4.15c — History now shows 2 entries (1 approved + 1 rejected)
- [ ] 4.16 — Verify history entries show correct timestamps (human readable, not ISO string)

### Edge cases

- [ ] 4.17 — Trigger 2 pipeline runs quickly → 2 pending cards should stack vertically
- [ ] 4.18 — Double-click Approve on a single card → second click should be no-op (button disabled during first call) or graceful 409 error shown
- [ ] 4.19 — Check browser console — zero JavaScript errors
- [ ] 4.20 — Check engine log — no Python tracebacks or unhandled exceptions
- [ ] 4.21 — Refresh the page → approval history persists (SQLite survived the page load)

---

## PHASE 5 — GIT COMMIT
*Only after all smoke tests pass.*

- [ ] 5.1 — Run secrets check: `bash scripts/hooks/check-secrets.sh` → must show no new secrets
- [ ] 5.2 — Stage new files:
  ```bash
  git add engine/approval/__init__.py
  git add engine/approval/store.py
  git add engine/approval/models.py
  git add engine/routers/approval_router.py
  git add engine/tests/test_approvals.py
  git add dashboard/components/ApprovalPanel.tsx
  ```
- [ ] 5.3 — Stage modified files:
  ```bash
  git add engine/main.py
  git add engine/routers/pipeline_router.py
  git add dashboard/lib/api.ts
  git add dashboard/app/command-center/page.tsx
  ```
- [ ] 5.4 — Review diff: `git diff --cached --stat` — should show exactly 10 files
- [ ] 5.5 — Commit:
  ```bash
  git commit -m "feat: add trade approval UI with SQLite-backed approval store

  - Add engine/approval/ package with ApprovalStore (SQLite, TTL 4hr)
  - Add /approvals router with 5 endpoints: pending, detail, approve, reject, history
  - Gate pipeline_router auto-log on requires_human flag
  - Add ApprovalPanel component with SWR polling (5s), Approve/Reject buttons
  - Mount ApprovalPanel on command-center page
  - Add 11 unit tests for approval store and endpoints

  Resolves P0 blocker: REQUIRE_HUMAN_APPROVAL=True now has a UI gate
  Sprint 12 TODO: wire approved decisions to IB Gateway order submission"
  ```
- [ ] 5.6 — Verify commit landed: `git log --oneline -3`

---

## TASK COUNT SUMMARY

| Phase | Tasks | Subtasks |
|-------|-------|---------|
| 1.1 — Create package | 1 | 4 |
| 1.2 — store.py | 1 | 70 |
| 1.3 — models.py | 1 | 30 |
| 1.4 — approvals_router.py | 1 | 45 |
| 1.5 — Wire main.py | 1 | 7 |
| 1.6 — Patch pipeline_router | 1 | 19 |
| 1.7 — Backend smoke test | 1 | 14 |
| 2.1 — TypeScript types | 1 | 31 |
| 2.2 — ApprovalPanel.tsx | 1 | 54 |
| 2.3 — Mount on command-center | 1 | 13 |
| 3.1 — test_approvals.py | 1 | 28 |
| 3.2 — Run test suite | 1 | 4 |
| 4 — Manual smoke test | 1 | 21 |
| 5 — Git commit | 1 | 6 |
| **TOTAL** | **14 tasks** | **346 subtasks** |

---

*Generated 2026-04-02 — Do not skip subtasks. Every checkbox is load-bearing.*
