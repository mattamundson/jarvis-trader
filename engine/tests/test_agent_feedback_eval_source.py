"""Regression tests for AgentFeedbackTracker.get_recent_trades_for_eval() —
the read accessor #644 (feat(llm): wire GEPA prompt-optimizer to real trade
outcomes) added for engine/llm/gepa_bindings.py's SqliteTradeEvalSource. This
method shipped with zero test coverage (post-merge review of #644).

DB-isolated: every test patches the module-level DB_PATH to a tmp file, the
same isolation pattern test_agent_feedback_dedup.py already established.
"""

from __future__ import annotations

import sqlite3
import sys
from unittest.mock import patch

from analytics.agent_feedback import AgentFeedbackTracker

# Patch the module the class actually lives in (robust to engine.* vs bare alias).
_AF_MOD = sys.modules[AgentFeedbackTracker.__module__]

_ANALYST_SIGNALS = {
    "technical": 0.6,
    "news": 0.2,
    "social": 0.0,
    "fundamental": 0.1,
    "corey": 0.3,
}


def _seed_raw(db_path, rows) -> None:
    """Insert rows directly, bypassing record_outcome()'s guards -- used to
    simulate a row shape the real write path structurally cannot produce
    (see test below), the same technique test_agent_feedback_dedup.py uses
    to simulate historical pollution."""
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO trade_outcomes "
            "(trade_id, timestamp, symbol, direction, pnl_usd, pnl_pct, outcome, "
            "technical_signal, news_signal, social_signal, fundamental_signal, "
            "corey_signal, breakout_signal, harmonic_signal, regime) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )


def test_get_recent_trades_for_eval_shapes_closed_realized_trades(tmp_path):
    """record_outcome() is the sole production writer of trade_outcomes, and
    it is only ever called from PortfolioTracker.close_paper_trade()'s
    post-close feedback hook -- i.e. every row it can produce is already a
    closed trade with a realized pnl_usd. get_recent_trades_for_eval() must
    faithfully surface those rows, correctly shaped for the GEPA optimizer's
    TradeEvalSource protocol (trade_id, symbol, timestamp, context, and the
    actual_winning_side derived from direction + outcome).
    """
    db = tmp_path / "agent_feedback.db"
    with patch.object(_AF_MOD, "DB_PATH", db):
        tracker = AgentFeedbackTracker()

        # A LONG trade that won -> actual_winning_side is LONG (its own side).
        tracker.record_outcome(
            trade_id="win-long",
            symbol="MES",
            direction="LONG",
            pnl_usd=125.50,
            analyst_signals=_ANALYST_SIGNALS,
        )
        # A SHORT trade that lost -> actual_winning_side is the OPPOSITE
        # side (LONG), not the trade's own direction.
        tracker.record_outcome(
            trade_id="loss-short",
            symbol="MES",
            direction="SHORT",
            pnl_usd=-80.0,
            analyst_signals=_ANALYST_SIGNALS,
        )

        rows = tracker.get_recent_trades_for_eval(limit=10)

    assert len(rows) == 2
    by_id = {r["trade_id"]: r for r in rows}
    assert set(by_id) == {"win-long", "loss-short"}

    win = by_id["win-long"]
    assert win["symbol"] == "MES"
    assert win["actual_winning_side"] == "LONG"
    assert win["pnl_usd"] == 125.50
    assert win["context"] == {
        "technical": 0.6, "news": 0.2, "social": 0.0,
        "fundamental": 0.1, "corey": 0.3,
    }

    loss = by_id["loss-short"]
    assert loss["actual_winning_side"] == "LONG"  # SHORT lost -> opposite (LONG) won
    assert loss["pnl_usd"] == -80.0

    # Every row returned is a closed, realized trade -- never a bare/None pnl.
    for row in rows:
        assert row["pnl_usd"] is not None
        assert isinstance(row["pnl_usd"], float)


def test_record_outcome_cannot_produce_an_unrealized_row(tmp_path):
    """record_outcome() compares pnl_usd > 0 before any other logic, so
    calling it with an unrealized/None pnl (what an 'open trade' snapshot
    would look like) raises rather than silently writing a row -- there is
    no production code path that can put an open/unrealized trade into
    trade_outcomes."""
    db = tmp_path / "agent_feedback.db"
    with patch.object(_AF_MOD, "DB_PATH", db):
        tracker = AgentFeedbackTracker()
        try:
            tracker.record_outcome(
                trade_id="still-open",
                symbol="MES",
                direction="LONG",
                pnl_usd=None,  # type: ignore[arg-type]
                analyst_signals=_ANALYST_SIGNALS,
            )
            raised = False
        except TypeError:
            raised = True

    assert raised, (
        "record_outcome() accepted a None (unrealized) pnl_usd without "
        "raising -- an open/unrealized trade could silently reach "
        "trade_outcomes and, from there, the GEPA optimizer's eval set."
    )


def test_get_recent_trades_for_eval_excludes_a_null_pnl_row(tmp_path):
    """Defensive belt-and-suspenders check: even if a NULL-pnl ('open
    trade') row ever lands in trade_outcomes via some path other than
    record_outcome() (e.g. a future writer or a legacy migration),
    get_recent_trades_for_eval() must not surface it to the optimizer."""
    db = tmp_path / "agent_feedback.db"
    with patch.object(_AF_MOD, "DB_PATH", db):
        tracker = AgentFeedbackTracker()  # creates the trade_outcomes table
        tracker.record_outcome(
            trade_id="closed-1",
            symbol="MES",
            direction="LONG",
            pnl_usd=42.0,
            analyst_signals=_ANALYST_SIGNALS,
        )
        _seed_raw(db, [(
            "open-unrealized", "2026-08-15T00:00:00+00:00", "MES", "LONG",
            None, None, None,  # pnl_usd, pnl_pct, outcome all unrealized
            0.5, 0.0, 0.0, 0.0, 0.0, None, None, None,
        )])

        rows = tracker.get_recent_trades_for_eval(limit=10)

    ids = {r["trade_id"] for r in rows}
    assert ids == {"closed-1"}
    assert "open-unrealized" not in ids
