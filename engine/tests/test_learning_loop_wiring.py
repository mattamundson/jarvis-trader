"""Roadmap 1.7 — close the review->improve learning dead-ends.

Three functions existed but were never actually exercised end-to-end in
production:

  1. ``feedback.process_trade_outcome`` generated a lesson and dropped it (the
     caller ``create_task``'d it and ignored the result).
  2. ``patterns.update_patterns_from_feedback`` had zero production callers AND
     could not have worked if called — it ``await``ed the db manager's
     ``fetch_one``/``execute``, but the live ``database/manager.py`` manager
     exposes those as SYNC methods (``await`` on a plain return raises).
  3. ``agents.post_mortem.PostTradeAnalyzer.analyze_trade`` had zero callers.

These tests lock in the fix: feedback now feeds the pattern library, the
persistence path tolerates both the sync (live) and async manager shapes via
``_maybe_await``, and the post-mortem analyzer persists a row given an injected
LLM. Hermetic: fake db managers + fake LLM, no config/network import beyond the
modules under test.
"""

import os
import sqlite3
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.feedback import process_trade_outcome  # noqa: E402
from learning.patterns import (  # noqa: E402
    _compute_pattern_hash,
    update_patterns_from_feedback,
)

_ENTRY = "2026-07-21T15:00:00+00:00"
_EXIT = "2026-07-21T15:30:00+00:00"


class _SyncFakeDB:
    """Emulates the live DatabaseManager: SYNC fetch_one/execute."""

    def __init__(self):
        self.executed = []  # list of (sql, params)
        self._rows = {}  # pattern_hash -> {"win_count", "loss_count"}

    def fetch_one(self, sql, params):
        if params and "trading_patterns" in sql:
            return self._rows.get(params[0])
        return None

    def execute(self, sql, params):
        self.executed.append((sql, params))
        return 1


class _AsyncFakeDB:
    """Emulates an async manager: coroutine fetch_one/execute."""

    def __init__(self):
        self.executed = []

    async def fetch_one(self, sql, params):
        return None

    async def execute(self, sql, params):
        self.executed.append((sql, params))
        return 1


def _inserts(executed):
    return [p for (s, p) in executed if "INSERT INTO trading_patterns" in s]


@pytest.mark.asyncio
async def test_feedback_feeds_patterns_sync_manager():
    """A winning close upserts trading_patterns through the SYNC manager path."""
    db = _SyncFakeDB()
    fb = await process_trade_outcome(
        trade_id="t-winner",
        symbol="MES",
        pnl=42.0,
        entry_price=5000.0,
        exit_price=5008.4,
        entry_time=_ENTRY,
        exit_time=_EXIT,
        action="buy",
        db_manager=db,
    )
    assert fb.lesson_type == "winning_trade"

    inserts = _inserts(db.executed)
    assert inserts, "expected trading_patterns INSERTs from a winning trade"
    pattern_types = {p[2] for p in inserts}  # params: (hash, symbol, pattern_type, ...)
    assert "MES_winner" in pattern_types
    assert "direction_pattern_LONG" in pattern_types
    for p in inserts:
        assert p[4] == 1  # win_count
        assert p[5] == 0  # loss_count


@pytest.mark.asyncio
async def test_patterns_upsert_async_manager():
    """_maybe_await handles the async manager shape too (a losing SHORT)."""
    db = _AsyncFakeDB()
    res = await update_patterns_from_feedback(
        {"symbol": "MGC", "pnl": -12.0, "action": "sell", "entry_time": _ENTRY},
        db_manager=db,
    )
    assert res is not None

    inserts = _inserts(db.executed)
    pattern_types = {p[2] for p in inserts}
    assert "MGC_loser" in pattern_types
    assert "direction_pattern_SHORT" in pattern_types
    for p in inserts:
        assert p[4] == 0  # win_count (loser)
        assert p[5] == 1  # loss_count


@pytest.mark.asyncio
async def test_patterns_update_accumulates_existing_sync():
    """A pre-existing pattern takes the UPDATE branch with accumulated counts."""
    db = _SyncFakeDB()
    h = _compute_pattern_hash("MES", "MES_winner")
    db._rows[h] = {"win_count": 3, "loss_count": 1}

    await update_patterns_from_feedback(
        {"symbol": "MES", "pnl": 10.0, "action": "buy", "entry_time": _ENTRY},
        db_manager=db,
    )

    updates = [
        p for (s, p) in db.executed if s.startswith("UPDATE trading_patterns")
    ]
    ours = [p for p in updates if p[-1] == h]
    assert ours, "expected an UPDATE for the pre-existing MES_winner pattern"
    # UPDATE params: (win_count, loss_count, win_rate, last_seen, pattern_hash)
    assert ours[0][0] == 4  # 3 existing + 1 new win
    assert ours[0][1] == 1  # loss_count unchanged


@pytest.mark.asyncio
async def test_feedback_without_db_returns_lesson_no_crash():
    """db_manager=None: lesson still generated, pattern persistence skipped."""
    fb = await process_trade_outcome(
        trade_id="t-nodb",
        symbol="MES",
        pnl=-5.0,
        entry_price=5000.0,
        exit_price=4999.0,
        entry_time=_ENTRY,
        exit_time="2026-07-21T15:10:00+00:00",
        action="buy",
        db_manager=None,
    )
    assert fb.lesson_type == "losing_trade"
    assert fb.symbol == "MES"


class _FileDB:
    """Minimal db surface PostTradeAnalyzer needs: _lock + _get_connection."""

    def __init__(self, path):
        self._path = str(path)
        self._lock = threading.Lock()

    def _get_connection(self):
        return sqlite3.connect(self._path)


class _FakeLLMResult:
    success = True

    def __init__(self, content):
        self.content = content


class _FakeLLM:
    def __init__(self):
        self.calls = []

    async def call(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeLLMResult(
            '{"analysis": "Trend-continuation thesis fired and paid.", '
            '"what_worked": "entry timing", "what_failed": "none material", '
            '"lesson": "Let winners run to the ATR target."}'
        )


@pytest.mark.asyncio
async def test_post_mortem_persists_row(tmp_path):
    """PostTradeAnalyzer writes a trade_post_mortem row given an injected LLM."""
    try:
        from agents.post_mortem import PostTradeAnalyzer
    except Exception as exc:  # pragma: no cover - env-dependent import chain
        pytest.skip(f"agents.post_mortem import unavailable in this env: {exc}")

    db_path = tmp_path / "pm.db"
    db = _FileDB(db_path)
    llm = _FakeLLM()
    analyzer = PostTradeAnalyzer(db, llm_client=llm)

    result = await analyzer.analyze_trade(
        "trade-xyz",
        {
            "symbol": "MES",
            "side": "buy",
            "quantity": 1,
            "entry_price": 5000.0,
            "exit_price": 5010.0,
            "pnl": 48.5,
            "exit_reason": "target",
        },
        {"regime": "TRENDING"},
    )
    assert "error" not in result
    assert result["lesson"]
    assert len(llm.calls) == 1

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT trade_id, symbol, pnl, lesson FROM trade_post_mortem WHERE trade_id = ?",
        ("trade-xyz",),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "trade-xyz"
    assert row[1] == "MES"
    assert abs(row[2] - 48.5) < 1e-9
    assert row[3]  # non-empty lesson persisted
