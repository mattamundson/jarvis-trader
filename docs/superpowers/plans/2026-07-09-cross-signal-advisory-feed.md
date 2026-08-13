# CROSS_SIGNAL Advisory Feed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface amo-arbitrage's ML signals as a clearly-labeled, non-authoritative `cross_signal_advisories` section of jarvis-trader's `GET /brief/session` response.

**Architecture:** A new `engine/integrations/amoarb_signals.py` module does one async HTTP GET (httpx, 5s timeout, never raises) against amo-arbitrage's existing `GET /api/signals/ml`. `engine/analytics/session_brief.py` stays pure — it gains one new optional keyword parameter (`cross_signals`, default `None`) that, when provided, is rendered into the response verbatim. `engine/routers/session_brief_router.py` is the only place that does I/O: it awaits the new fetch alongside the existing snapshot collection and passes the result through.

**Tech Stack:** Python 3.12, FastAPI, httpx (already a project dependency, used identically in `routers/health_router.py`), pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-09-cross-signal-advisory-feed-design.md`.
- `engine/analytics/session_brief.py` must remain a pure module — no I/O, no engine imports (per its own module docstring).
- Default parameter values must make every existing caller's output byte-identical to today (no `cross_signals` arg passed anywhere yet outside the router).
- No file under `engine/risk/`, `engine/config.py`, or execution/kill-switch code is touched — no `[safety-review]` PR tag needed.
- ruff-clean, type hints on public functions (per `engine-python.md`).
- Runtime: `engine/.venv/Scripts/python` only.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `engine/integrations/__init__.py` | Create | New package marker (first file in a new `integrations/` directory) |
| `engine/integrations/amoarb_signals.py` | Create | HTTP client for amo-arbitrage's `GET /api/signals/ml`; never raises |
| `engine/tests/test_amoarb_signals.py` | Create | Unit tests for the client: happy path, timeout, connection error, malformed JSON |
| `engine/analytics/session_brief.py` | Modify | Add `cross_signals` param to `build_session_brief()`; render `cross_signal_advisories` key |
| `engine/tests/test_session_brief.py` | Modify | Add cases for `cross_signals` present/absent |
| `engine/routers/session_brief_router.py` | Modify | Await `fetch_amoarb_signals()` alongside `_collect_snapshots()`; pass through |

---

### Task 1: amo-arbitrage signal client

**Files:**
- Create: `engine/integrations/__init__.py`
- Create: `engine/integrations/amoarb_signals.py`
- Test: `engine/tests/test_amoarb_signals.py`

**Interfaces:**
- Produces: `async def fetch_amoarb_signals() -> dict` returning `{"available": bool, "signals": list[dict], "error": str | None, "fetched_at": str}`. Never raises.

- [ ] **Step 1: Write the failing tests**

```python
# engine/tests/test_amoarb_signals.py
"""
Tests for the amo-arbitrage signal client (integrations.amoarb_signals).

Covers the invariant this module exists for: it NEVER raises, regardless of
what amo-arbitrage's endpoint does (down, slow, malformed) -- a dead upstream
must degrade to an honest {available: False, error: ...}, never take down
jarvis-trader's own /brief/session.
"""

from __future__ import annotations

import httpx
import pytest

from integrations.amoarb_signals import fetch_amoarb_signals


class _MockResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


class _MockAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, *args, **kwargs):
        return _MockAsyncClient._next_response


@pytest.mark.asyncio
async def test_happy_path(monkeypatch):
    rows = [
        {"symbol": "ZC", "signal": "buy", "prob_up": 0.61, "ic_overall": 0.08,
         "win_rate_oos": 0.54, "signal_date": "2026-07-09"},
    ]
    _MockAsyncClient._next_response = _MockResponse(rows)
    monkeypatch.setattr(httpx, "AsyncClient", _MockAsyncClient)

    result = await fetch_amoarb_signals()

    assert result["available"] is True
    assert result["signals"] == rows
    assert result["error"] is None
    assert result["fetched_at"]


@pytest.mark.asyncio
async def test_connection_error(monkeypatch):
    class _RaisingClient(_MockAsyncClient):
        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "AsyncClient", _RaisingClient)

    result = await fetch_amoarb_signals()

    assert result["available"] is False
    assert result["signals"] == []
    assert "connection" in result["error"].lower() or result["error"]


@pytest.mark.asyncio
async def test_timeout(monkeypatch):
    class _TimeoutClient(_MockAsyncClient):
        async def get(self, *args, **kwargs):
            raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "AsyncClient", _TimeoutClient)

    result = await fetch_amoarb_signals()

    assert result["available"] is False
    assert result["error"]


@pytest.mark.asyncio
async def test_malformed_json(monkeypatch):
    class _BadJsonResponse(_MockResponse):
        def json(self):
            raise ValueError("not JSON")

    _MockAsyncClient._next_response = _BadJsonResponse(None)
    monkeypatch.setattr(httpx, "AsyncClient", _MockAsyncClient)

    result = await fetch_amoarb_signals()

    assert result["available"] is False
    assert result["signals"] == []
    assert result["error"]


@pytest.mark.asyncio
async def test_non_200_status(monkeypatch):
    _MockAsyncClient._next_response = _MockResponse({"detail": "error"}, status_code=500)
    monkeypatch.setattr(httpx, "AsyncClient", _MockAsyncClient)

    result = await fetch_amoarb_signals()

    assert result["available"] is False
    assert result["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd engine && .venv/Scripts/python -m pytest tests/test_amoarb_signals.py -v`
Expected: FAIL (collection error) with `ModuleNotFoundError: No module named 'integrations'`

- [ ] **Step 3: Write the implementation**

```python
# engine/integrations/__init__.py
```
(empty — package marker)

```python
# engine/integrations/amoarb_signals.py
"""
Read-only client for amo-arbitrage's ML signal feed (GET /api/signals/ml).

Advisory only: this module NEVER feeds jarvis-trader's own trade/risk/fund
decisions -- it exists purely to surface amo-arbitrage's signals as an
informational cross-system data point in the session brief (see
analytics/session_brief.py's `cross_signals` parameter). Async with graceful
fallback per engine-python.md: any failure (timeout, connection error,
non-2xx, malformed JSON) degrades to an explicit "not available" result --
this function NEVER raises past its own boundary.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

AMOARB_SIGNALS_URL = os.environ.get(
    "AMOARB_SIGNALS_URL", "http://127.0.0.1:8000/api/signals/ml"
)
AMOARB_SIGNALS_TIMEOUT_S = 5.0


async def fetch_amoarb_signals() -> dict[str, Any]:
    """Fetch the latest amo-arbitrage ML signals. Never raises.

    Returns:
        {"available": bool, "signals": list[dict], "error": str | None,
         "fetched_at": str (ISO-8601 UTC)}
    """
    import httpx  # lazy import per engine-python.md

    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        async with httpx.AsyncClient(timeout=AMOARB_SIGNALS_TIMEOUT_S) as client:
            response = await client.get(AMOARB_SIGNALS_URL)
        response.raise_for_status()
        signals = response.json()
        if not isinstance(signals, list):
            raise ValueError(f"expected a list, got {type(signals).__name__}")
        return {
            "available": True,
            "signals": signals,
            "error": None,
            "fetched_at": fetched_at,
        }
    except Exception as exc:  # never let a dead amo-arbitrage break the caller
        logger.warning("[amoarb_signals] fetch failed: %s", exc)
        return {
            "available": False,
            "signals": [],
            "error": str(exc)[:200],
            "fetched_at": fetched_at,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd engine && .venv/Scripts/python -m pytest tests/test_amoarb_signals.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/integrations/__init__.py engine/integrations/amoarb_signals.py engine/tests/test_amoarb_signals.py
git commit -m "feat(integrations): add amo-arbitrage signal client

Read-only, never-raising HTTP client for amo-arbitrage's GET
/api/signals/ml. Advisory data source only -- does not feed any
trade/risk/fund decision. Part of the CROSS_SIGNAL advisory feed
(docs/superpowers/specs/2026-07-09-cross-signal-advisory-feed-design.md)."
```

---

### Task 2: session_brief cross_signals parameter

**Files:**
- Modify: `engine/analytics/session_brief.py`
- Test: `engine/tests/test_session_brief.py`

**Interfaces:**
- Consumes: nothing new (still a pure formatter — takes whatever dict shape `fetch_amoarb_signals()` produces, from Task 1, but does not import or call it).
- Produces: `build_session_brief(snapshots, *, now=None, max_actions=DEFAULT_MAX_ACTIONS, stale_after_s=DEFAULT_STALE_AFTER_S, dedupe_by_symbol=True, cross_signals: dict | None = None) -> dict`. When `cross_signals` is not `None`, the returned dict gains a `cross_signal_advisories` key.

- [ ] **Step 1: Write the failing tests**

Append to `engine/tests/test_session_brief.py`:

```python
def test_cross_signals_absent_is_unchanged():
    """Default (no cross_signals arg) must not add the new key -- backward compat."""
    brief = build_session_brief([_full_snapshot()], now=NOW)
    assert "cross_signal_advisories" not in brief


def test_cross_signals_available():
    cross_signals = {
        "available": True,
        "signals": [{"symbol": "ZC", "signal": "buy", "prob_up": 0.61}],
        "error": None,
        "fetched_at": "2026-07-09T12:00:00+00:00",
    }
    brief = build_session_brief([_full_snapshot()], now=NOW, cross_signals=cross_signals)

    advisories = brief["cross_signal_advisories"]
    assert advisories["source"] == "amo-arbitrage"
    assert advisories["available"] is True
    assert advisories["signals"] == cross_signals["signals"]
    assert advisories["note"] is None


def test_cross_signals_unavailable_is_honest_not_fabricated():
    cross_signals = {
        "available": False,
        "signals": [],
        "error": "connection refused",
        "fetched_at": "2026-07-09T12:00:00+00:00",
    }
    brief = build_session_brief([_full_snapshot()], now=NOW, cross_signals=cross_signals)

    advisories = brief["cross_signal_advisories"]
    assert advisories["available"] is False
    assert "signals" not in advisories
    assert advisories["note"] is not None
    assert "not fabricating" in advisories["note"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd engine && .venv/Scripts/python -m pytest tests/test_session_brief.py -k cross_signals -v`
Expected: FAIL with `TypeError: build_session_brief() got an unexpected keyword argument 'cross_signals'`

- [ ] **Step 3: Write the implementation**

In `engine/analytics/session_brief.py`, change the signature and body of `build_session_brief` (existing function, currently at line 180):

```python
def build_session_brief(
    snapshots: Any,
    *,
    now: Optional[datetime] = None,
    max_actions: int = DEFAULT_MAX_ACTIONS,
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
    dedupe_by_symbol: bool = True,
    cross_signals: Optional[dict] = None,
) -> dict:
    """Assemble a session brief from newest-first pipeline snapshots.

    Returns ``{generated_at, actions, count, degraded, note}``, plus an
    additive ``cross_signal_advisories`` key when ``cross_signals`` is
    provided. When there are no usable snapshots, ``actions`` is empty and
    ``note`` explains the gap -- the brief is honest about having nothing to
    say rather than inventing content. Same philosophy applies to
    ``cross_signal_advisories``: an unavailable feed says so, never silently
    fabricated.
    """
    now = now or datetime.now(timezone.utc)
    generated_at = now.isoformat()
    max_actions = max(1, int(max_actions))

    if not isinstance(snapshots, (list, tuple)) or not snapshots:
        brief = {
            "generated_at": generated_at,
            "actions": [],
            "count": 0,
            "degraded": True,
            "note": "No recent pipeline snapshots available to build a brief.",
        }
    else:
        actions: list[dict] = []
        seen_symbols: set[str] = set()
        for snap in snapshots:
            built = build_action(snap, now=now, stale_after_s=stale_after_s)
            if built is None:
                continue
            if dedupe_by_symbol:
                sym = built["symbol"]
                if sym in seen_symbols:
                    continue
                seen_symbols.add(sym)
            actions.append(built)

        actions.sort(key=_action_sort_key)
        actions = actions[:max_actions]

        degraded = (not actions) or any(a["data_degraded"] for a in actions)
        note = None
        if not actions:
            note = "No pipeline snapshots yielded a usable recommended action."

        brief = {
            "generated_at": generated_at,
            "actions": actions,
            "count": len(actions),
            "degraded": degraded,
            "note": note,
        }

    if cross_signals is not None:
        brief["cross_signal_advisories"] = _build_cross_signal_advisories(cross_signals)

    return brief


def _build_cross_signal_advisories(cross_signals: dict) -> dict:
    """Render a pre-fetched amo-arbitrage signal result. Pure -- takes the
    dict integrations.amoarb_signals.fetch_amoarb_signals() already produced,
    does no I/O itself. Never fabricates: an unavailable feed says so."""
    available = bool(cross_signals.get("available"))
    if not available:
        return {
            "source": "amo-arbitrage",
            "available": False,
            "note": "amo-arbitrage signal feed unreachable -- not fabricating signal data.",
        }
    return {
        "source": "amo-arbitrage",
        "available": True,
        "signals": cross_signals.get("signals", []),
        "note": None,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd engine && .venv/Scripts/python -m pytest tests/test_session_brief.py -v`
Expected: PASS (all existing tests still pass + 3 new ones)

- [ ] **Step 5: Commit**

```bash
git add engine/analytics/session_brief.py engine/tests/test_session_brief.py
git commit -m "feat(analytics): add optional cross_signal_advisories to session brief

build_session_brief() gains a cross_signals kwarg (default None -- every
existing caller's output is byte-identical). When provided, renders a
clearly-separated cross_signal_advisories key so amo-arbitrage data can
never be mistaken for a jarvis-trader recommendation. Stays a pure
formatter -- no I/O added."
```

---

### Task 3: wire the router

**Files:**
- Modify: `engine/routers/session_brief_router.py`

**Interfaces:**
- Consumes: `fetch_amoarb_signals()` from Task 1 (`engine/integrations/amoarb_signals.py`), `build_session_brief(..., cross_signals=...)` from Task 2.

- [ ] **Step 1: Write the failing test**

There is no existing router-level test file for `/brief/session` (the router is covered by the pure-function tests above plus the live endpoint). Verify this task by hand via Step 4 (live call), which is the same verification level the router's only current safety net (manual/health-check) already uses. No new test file needed for this step — the router change is a thin wire-up already covered by Tasks 1 and 2's unit tests plus a live check.

- [ ] **Step 2: N/A** (no failing test to run for this task — see Step 1)

- [ ] **Step 3: Write the implementation**

In `engine/routers/session_brief_router.py`, add the import and update `get_session_brief`:

```python
from analytics.session_brief import DEFAULT_MAX_ACTIONS, build_session_brief
from integrations.amoarb_signals import fetch_amoarb_signals
```

```python
@router.get("/session")
async def get_session_brief(limit: int = 10, max_actions: int = DEFAULT_MAX_ACTIONS):
    """Return a proactive advisor brief built from existing pipeline reasoning,
    plus an advisory (non-authoritative) amo-arbitrage signal section.

    Query params:
        limit       : how many recent decisions to scan (1-50).
        max_actions : cap on recommended actions in the brief (1-5).
    """
    try:
        limit = min(max(1, int(limit)), 50)
        max_actions = min(max(1, int(max_actions)), 5)
        snapshots = _collect_snapshots(limit)
        cross_signals = await fetch_amoarb_signals()
        return build_session_brief(snapshots, max_actions=max_actions, cross_signals=cross_signals)
    except Exception as exc:  # fail honest, never 500 on brief assembly
        logger.exception("[brief] session brief assembly failed")
        raise HTTPException(status_code=500, detail=f"brief assembly failed: {exc}") from exc
```

- [ ] **Step 4: Verify live**

Run: `cd engine && .venv/Scripts/python -m pytest tests/ -v` (full suite — confirms nothing else broke)
Expected: PASS, 0 failures

Then, with the engine running (`.\restart_engine.ps1`), verify the endpoint directly:
```bash
curl http://127.0.0.1:8010/brief/session -H "X-API-Key: <value from engine/.env>"
```
Expected: JSON response containing a `cross_signal_advisories` key with either real amo-arbitrage signals (if that backend is up on port 8000) or `{"available": false, "note": "amo-arbitrage signal feed unreachable -- not fabricating signal data."}` (if it's down) — either way, the existing `actions` key is present and unchanged in shape.

- [ ] **Step 5: Commit**

```bash
git add engine/routers/session_brief_router.py
git commit -m "feat(routers): wire amo-arbitrage signals into /brief/session

Awaits fetch_amoarb_signals() alongside the existing snapshot collection;
either can fail independently without affecting the other. Completes the
CROSS_SIGNAL advisory feed
(docs/superpowers/specs/2026-07-09-cross-signal-advisory-feed-design.md)."
```

---

## Self-Review

**Spec coverage:** Architecture (Task 1+2+3 match the spec's three-component diagram exactly), Components section (client module, session_brief param, router wiring — each is its own task), Error handling (never-raises client + honest `note` when unavailable — covered in Task 1 and Task 2 tests), Testing section (client unit tests, session_brief unit tests — both present; explicitly no live-amo-arbitrage integration test, matching the spec's stated choice). Rollout (single PR, no config beyond optional env var, no safety-review tag) — satisfied by these three tasks being the whole change.

**Placeholder scan:** No TBD/TODO. Task 3 Step 1/2 deliberately explain why there's no new test file for that task rather than gesturing at one — this is a real project decision (thin wiring, already covered by the other two tasks' unit tests), not a placeholder.

**Type consistency:** `fetch_amoarb_signals()` (Task 1) returns exactly the dict shape `_build_cross_signal_advisories()` (Task 2) consumes (`available`, `signals`, `error`, `fetched_at`) — checked against both implementations above, keys match. `build_session_brief`'s new `cross_signals` parameter name matches what Task 3's router passes as a keyword argument.
