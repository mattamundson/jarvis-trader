"""Integration: the paper-close -> trade_outcomes wiring (2026-06-05 repair).

Proves a trade carrying analyst_signals in strategy_params writes a
trade_outcomes row on close -- the exact path that silently no-op'd before
US-001/US-002, because the scanner and open_trade never persisted the signals.
DB-isolated via tmp_path + DB_PATH patch.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from unittest.mock import patch

from engine.analytics.agent_feedback import AgentFeedbackTracker
from engine.portfolio.tracker import PaperTrade, PortfolioTracker

_AF_MOD = sys.modules[AgentFeedbackTracker.__module__]


class _FakeDB:
    """Minimal stand-in: only get_trade_by_id is exercised by the close path."""

    def __init__(self, row):
        self._row = row

    def get_trade_by_id(self, trade_id):
        return self._row


def _trade(**kw):
    base = {
        "trade_id": "t-xyz",
        "symbol": "MGC",
        "action": "buy",
        "quantity": 1.0,
        "entry_price": 2000.0,
        "entry_time": "2026-06-05T12:00:00+00:00",
        "pnl": 120.0,
        "is_open": False,
    }
    base.update(kw)
    return PaperTrade(**base)


def test_close_with_signals_writes_trade_outcome(tmp_path, monkeypatch):
    monkeypatch.delenv("TESTING", raising=False)  # conftest sets it; close path no-ops while set
    db = tmp_path / "agent_feedback.db"
    with patch.object(_AF_MOD, "DB_PATH", db):
        tracker = PortfolioTracker(store_path=tmp_path / "store.jsonl", db_manager=None)
        tracker._db = _FakeDB(
            {
                "strategy_params": json.dumps(
                    {
                        "analyst_signals": {"technical": 0.8, "news": -0.3},
                        "regime": "trend",
                    }
                )
            }
        )
        tracker._record_agent_feedback("t-xyz", _trade(pnl=120.0))
        with sqlite3.connect(db) as c:
            rows = c.execute(
                "SELECT symbol, direction, pnl_usd, outcome, technical_signal, news_signal "
                "FROM trade_outcomes"
            ).fetchall()
    assert len(rows) == 1
    assert rows[0] == ("MGC", "LONG", 120.0, "WIN", 0.8, -0.3)


def test_close_without_signals_is_noop(tmp_path, monkeypatch):
    monkeypatch.delenv("TESTING", raising=False)
    db = tmp_path / "agent_feedback.db"
    with patch.object(_AF_MOD, "DB_PATH", db):
        tracker = PortfolioTracker(store_path=tmp_path / "store.jsonl", db_manager=None)
        tracker._db = _FakeDB({"strategy_params": json.dumps({"regime": "trend"})})
        tracker._record_agent_feedback("t-xyz", _trade())
        with sqlite3.connect(db) as c:
            try:
                n = c.execute("SELECT COUNT(*) FROM trade_outcomes").fetchone()[0]
            except sqlite3.OperationalError:
                n = 0
    assert n == 0


