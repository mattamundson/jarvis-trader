"""
End-to-end integration test for the Brier calibration full loop (Novel #2).

Exercises the complete path:
  1. Open a paper trade with analyst_signals persisted in strategy_params
  2. Close the trade → PortfolioTracker._record_agent_feedback fires
  3. AgentFeedbackTracker.record_outcome writes a row to trade_outcomes
  4. BrierCalibrationTracker pointed at the same DB can now read the row and
     compute a non-neutral weight for the agent whose signal matched P&L

This is the "pipe is live" proof: after this passes, the calibration subsystem
is no longer dark — closed trades actually produce the feedback signal both
trackers need.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from database.manager import DatabaseManager
from portfolio.tracker import PortfolioTracker


def _init_feedback_schema(db_path: Path) -> None:
    """Mirror the AgentFeedbackTracker._init_db schema so BrierCalibrationTracker
    can read even when no rows have been inserted yet."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_outcomes (
                trade_id TEXT PRIMARY KEY,
                timestamp TEXT,
                symbol TEXT,
                direction TEXT,
                pnl_usd REAL,
                pnl_pct REAL,
                outcome TEXT,
                technical_signal REAL,
                news_signal REAL,
                social_signal REAL,
                fundamental_signal REAL,
                corey_signal REAL
            )
        """)


def test_closed_trade_writes_feedback_and_brier_reads_it(tmp_path, monkeypatch):
    # ── Arrange ──────────────────────────────────────────────────────────────
    # Redirect AgentFeedbackTracker + BrierCalibrationTracker to a temp DB
    feedback_db = tmp_path / "agent_feedback.db"
    _init_feedback_schema(feedback_db)

    # The tracker's close hook imports via `engine.analytics.agent_feedback`
    # (absolute path from project root) — that's a distinct sys.modules entry
    # from `analytics.agent_feedback`. Patch both to cover direct and
    # absolute-path resolution (unit tests use the short path; production uses
    # the engine. prefix).
    import engine.analytics.agent_feedback as af_eng
    import engine.analytics.ic_ensemble as ic_eng

    import analytics.agent_feedback as af_short
    import analytics.ic_ensemble as ic_short

    monkeypatch.setattr(af_short, "DB_PATH", feedback_db)
    monkeypatch.setattr(af_eng, "DB_PATH", feedback_db)
    monkeypatch.setattr(ic_short, "_DEFAULT_DB_PATH", feedback_db)
    monkeypatch.setattr(ic_eng, "_DEFAULT_DB_PATH", feedback_db)

    # The close-hook short-circuits when TESTING is set (conftest sets it);
    # unset for this integration test so the write path actually runs.
    monkeypatch.delenv("TESTING", raising=False)

    # Tracker wired to a real DatabaseManager (so strategy_params persists)
    paper_db_path = tmp_path / "paper.db"
    db = DatabaseManager(str(paper_db_path))
    db.initialize()
    tracker = PortfolioTracker(
        store_path=tmp_path / "paper_trades.jsonl",
        db_manager=db,
    )

    # ── Act: open a trade carrying analyst signals ───────────────────────────
    # technical agrees with the upcoming winning direction; news disagrees.
    analyst_signals = {
        "technical": 0.8,   # bullish, will be right
        "news": -0.6,       # bearish, will be wrong
        "social": 0.0,
        "fundamental": 0.0,
        "corey": 0.0,
    }
    trade_id = tracker.add_paper_trade(
        symbol="MCL",
        side="buy",
        quantity=1.0,
        entry_price=80.00,
        stop_loss=78.00,
        take_profit=85.00,
        strategy_params={
            "source": "test",
            "predicted_direction": "LONG",
            "analyst_signals": analyst_signals,
        },
    )

    # Close with a win (exit > entry for a long)
    closed = tracker.close_trade(trade_id, exit_price=82.50)
    assert closed.pnl is not None and closed.pnl > 0

    # ── Assert: trade_outcomes row was written ───────────────────────────────
    with sqlite3.connect(feedback_db) as conn:
        rows = conn.execute(
            "SELECT trade_id, symbol, direction, pnl_usd, outcome, "
            "technical_signal, news_signal FROM trade_outcomes "
            "WHERE trade_id = ?",
            (trade_id,),
        ).fetchall()

    assert len(rows) == 1, "record_outcome did not write to trade_outcomes"
    row = rows[0]
    assert row[0] == trade_id
    assert row[1] == "MCL"
    assert row[2] == "LONG"
    assert row[3] > 0              # pnl_usd positive
    assert row[4] == "WIN"
    assert row[5] == pytest.approx(0.8)   # technical_signal preserved
    assert row[6] == pytest.approx(-0.6)  # news_signal preserved (wrong call)

    # ── Assert: BrierCalibrationTracker picks up the row ─────────────────────
    # With only 1 trade we're below min_trades=5 so compute_brier returns the
    # neutral sentinel (0.25). The meaningful invariant is that the DB path
    # resolves and the tracker can read without error — plus the signal math
    # mirror via direct Brier computation.
    from analytics.ic_ensemble import BrierCalibrationTracker

    brier = BrierCalibrationTracker(
        db_path=str(feedback_db),
        agents=["technical", "news", "social", "fundamental", "corey"],
        min_trades=1,  # relax threshold so single-row test reflects actual math
    )
    briers = brier.get_brier_summary()

    # technical: signal=0.8, outcome=1 (win) → p=(0.8+1)/2=0.9, brier=(0.9-1)^2=0.01
    assert briers["technical"] == pytest.approx(0.01, abs=1e-6)
    # news: signal=-0.6, outcome=1 (win) → p=(-0.6+1)/2=0.2, brier=(0.2-1)^2=0.64
    assert briers["news"] == pytest.approx(0.64, abs=1e-6)

    weights = brier.get_calibration_weights()
    # technical must outweigh news after one correct-vs-wrong outcome
    assert weights["technical"] > weights["news"]


def test_close_without_analyst_signals_is_safe_noop(tmp_path, monkeypatch):
    """Legacy trades opened before this change have no analyst_signals;
    the close hook must skip silently (no crash, no row written)."""
    feedback_db = tmp_path / "agent_feedback.db"
    _init_feedback_schema(feedback_db)

    import engine.analytics.agent_feedback as af_eng

    import analytics.agent_feedback as af_short
    monkeypatch.setattr(af_short, "DB_PATH", feedback_db)
    monkeypatch.setattr(af_eng, "DB_PATH", feedback_db)
    monkeypatch.delenv("TESTING", raising=False)

    paper_db_path = tmp_path / "paper.db"
    db = DatabaseManager(str(paper_db_path))
    db.initialize()
    tracker = PortfolioTracker(
        store_path=tmp_path / "paper_trades.jsonl",
        db_manager=db,
    )

    trade_id = tracker.add_paper_trade(
        symbol="MCL",
        side="buy",
        quantity=1.0,
        entry_price=80.00,
        strategy_params={"source": "legacy"},  # no analyst_signals key
    )
    tracker.close_trade(trade_id, exit_price=82.50)

    with sqlite3.connect(feedback_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM trade_outcomes").fetchone()[0]
    assert count == 0, "legacy close must not write to trade_outcomes"
