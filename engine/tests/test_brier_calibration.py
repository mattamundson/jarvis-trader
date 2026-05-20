"""
Unit tests for BrierCalibrationTracker.

Brier scoring interpretation
----------------------------
For each trade, each agent's signal s ∈ [-1, 1] is decomposed into:
  confidence = |s|
  correct    = 1 if sign(s) == sign(pnl) else 0
  brier_i    = (confidence - correct)²

Lower Brier = better calibrated. A confident-and-wrong agent gets the
maximum penalty (brier = 1.0); a cautious agent (|s|→0) is penalized
at most 0.0 when right and 0.0 when wrong — low risk, low reward.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from analytics.ic_ensemble import BrierCalibrationTracker


def _seed_trades(db_path: Path, rows):
    """Seed a minimal trade_outcomes table matching AgentFeedbackTracker schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
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
        """
        )
        for row in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO trade_outcomes
                (trade_id, timestamp, symbol, direction, pnl_usd, pnl_pct, outcome,
                 technical_signal, news_signal, social_signal, fundamental_signal, corey_signal)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )


def _mk_rows(agent_col_index, signals_and_pnls, now_iso="2026-04-16T12:00:00+00:00"):
    """
    Build rows varying only one agent's signal column.
    signals_and_pnls: iterable of (signal, pnl_usd) tuples.
    """
    rows = []
    defaults = [0.0, 0.0, 0.0, 0.0, 0.0]  # technical, news, social, fundamental, corey
    for i, (sig, pnl) in enumerate(signals_and_pnls):
        sigs = list(defaults)
        sigs[agent_col_index] = sig
        rows.append(
            (
                f"t{i:03d}",
                now_iso,
                "MCL",
                "LONG" if pnl >= 0 else "SHORT",
                pnl,
                0.0,
                "WIN" if pnl > 0 else "LOSS",
                *sigs,
            )
        )
    return rows


@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "agent_feedback.db"


def test_perfect_calibration_low_brier(tmp_db):
    # Agent 0 (technical) always signals with high confidence matching the outcome.
    rows = _mk_rows(
        0,
        [
            (0.9, 50.0),
            (0.9, 40.0),
            (-0.9, -30.0),
            (-0.9, -60.0),
            (0.8, 20.0),
            (0.8, 45.0),
        ],
    )
    _seed_trades(tmp_db, rows)
    tracker = BrierCalibrationTracker(db_path=str(tmp_db), min_trades=5)
    brier = tracker.compute_brier("technical")
    # Perfect direction agreement, confidence ~0.85 → brier = (0.85 - 1)² ≈ 0.0225
    assert brier < 0.05, f"Expected near-zero Brier, got {brier}"


def test_confident_and_wrong_high_brier(tmp_db):
    # Agent shouts +0.95 but loses every trade.
    rows = _mk_rows(
        0,
        [
            (0.95, -50.0),
            (0.95, -20.0),
            (0.9, -30.0),
            (0.9, -10.0),
            (0.85, -40.0),
            (0.8, -25.0),
        ],
    )
    _seed_trades(tmp_db, rows)
    tracker = BrierCalibrationTracker(db_path=str(tmp_db), min_trades=5)
    brier = tracker.compute_brier("technical")
    # Confident wrong: brier ≈ 0.9² ≈ 0.81
    assert brier > 0.70, f"Expected high Brier, got {brier}"


def test_cautious_agent_middling_brier(tmp_db):
    # Signal magnitude ~0.1 regardless of outcome — Brier stays low either way.
    rows = _mk_rows(
        0,
        [
            (0.1, 50.0),
            (0.1, -30.0),
            (-0.1, 20.0),
            (-0.1, -40.0),
            (0.1, -10.0),
            (0.1, 5.0),
        ],
    )
    _seed_trades(tmp_db, rows)
    tracker = BrierCalibrationTracker(db_path=str(tmp_db), min_trades=5)
    brier = tracker.compute_brier("technical")
    # Low-confidence: brier bounded around |0.1 - 0|² = 0.01 or |0.1 - 1|² = 0.81.
    # Average across mixed outcomes lands in a middling range.
    assert 0.0 < brier < 1.0


def test_insufficient_data_returns_neutral(tmp_db):
    rows = _mk_rows(0, [(0.5, 10.0), (0.5, -5.0)])  # only 2 trades
    _seed_trades(tmp_db, rows)
    tracker = BrierCalibrationTracker(db_path=str(tmp_db), min_trades=5)
    brier = tracker.compute_brier("technical")
    # Neutral / unknown sentinel — must NOT be 0.0 (that would mean perfect calibration).
    assert brier == 0.25, f"Expected neutral 0.25 sentinel, got {brier}"


def test_missing_db_is_graceful(tmp_path):
    tracker = BrierCalibrationTracker(db_path=str(tmp_path / "does-not-exist.db"))
    assert tracker.compute_brier("technical") == 0.25


def test_brier_weights_reward_calibration(tmp_db):
    # technical (col 0): perfect calibration. news (col 1): confident+wrong.
    rows = []
    rows += _mk_rows(
        0,
        [
            (0.9, 50.0),
            (0.9, 40.0),
            (-0.9, -30.0),
            (-0.9, -60.0),
            (0.8, 20.0),
            (0.8, 45.0),
        ],
    )
    # Re-seed with news_signal populated on distinct trade_ids.
    bad_rows = _mk_rows(
        1,
        [
            (0.95, -50.0),
            (0.95, -20.0),
            (0.9, -30.0),
            (0.9, -10.0),
            (0.85, -40.0),
            (0.8, -25.0),
        ],
    )
    # Offset ids so they don't collide with the first batch.
    bad_rows = [(f"b{r[0]}", *r[1:]) for r in bad_rows]
    rows += bad_rows
    _seed_trades(tmp_db, rows)

    tracker = BrierCalibrationTracker(db_path=str(tmp_db), min_trades=5)
    weights = tracker.get_calibration_weights(["technical", "news"])
    # Both weights sum to 1.0 and technical dominates.
    assert pytest.approx(sum(weights.values()), abs=1e-6) == 1.0
    assert weights["technical"] > weights["news"]
    assert weights["technical"] > 0.75


def test_zero_signal_trades_excluded(tmp_db):
    # Trades where the agent had no opinion (signal=0) must not inflate Brier.
    rows = _mk_rows(
        0,
        [
            (0.0, 50.0),  # no-opinion trade — should be skipped
            (0.0, -20.0),
            (0.9, 40.0),
            (0.9, 30.0),
            (-0.9, -10.0),
            (-0.8, -25.0),
            (0.8, 15.0),
        ],
    )
    _seed_trades(tmp_db, rows)
    tracker = BrierCalibrationTracker(db_path=str(tmp_db), min_trades=5)
    brier = tracker.compute_brier("technical")
    # Only the 5 non-zero trades count; all well-calibrated.
    assert brier < 0.06


def _fresh_iso():
    """Inside-window timestamp so the rolling 30d filter doesn't drop the row."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def test_rolling_brier_excludes_cold_start_agents(tmp_db):
    # technical has 6 closed signals (calibrated); news has 0 (cold start).
    # Rolling 30d Brier should mirror technical's score, NOT average in
    # news's BRIER_NEUTRAL sentinel — otherwise the system score would
    # anchor at 0.25 forever until every agent has data.
    rows = _mk_rows(
        0,
        [
            (0.9, 50.0),
            (0.9, 40.0),
            (-0.9, -30.0),
            (-0.9, -60.0),
            (0.8, 20.0),
            (0.8, 45.0),
        ],
        now_iso=_fresh_iso(),
    )
    _seed_trades(tmp_db, rows)
    tracker = BrierCalibrationTracker(db_path=str(tmp_db), min_trades=5)
    rolling = tracker.compute_rolling_brier()
    assert rolling is not None
    # Should match the technical agent's Brier — close to perfect.
    assert rolling < 0.05, f"Expected low rolling Brier, got {rolling}"


def test_rolling_brier_none_when_no_agent_has_data(tmp_path):
    # Empty DB → no agent meets min_trades → /health surface returns None,
    # NOT 0.0 (which would falsely imply perfect calibration).
    tracker = BrierCalibrationTracker(db_path=str(tmp_path / "empty.db"), min_trades=5)
    assert tracker.compute_rolling_brier() is None


def test_rolling_brier_averages_across_multiple_agents(tmp_db):
    # technical (col 0): well-calibrated. news (col 1): confidently wrong.
    fresh = _fresh_iso()
    rows = _mk_rows(
        0,
        [
            (0.9, 50.0),
            (0.9, 40.0),
            (-0.9, -30.0),
            (-0.9, -60.0),
            (0.8, 20.0),
            (0.8, 45.0),
        ],
        now_iso=fresh,
    )
    bad_rows = _mk_rows(
        1,
        [
            (0.95, -50.0),
            (0.95, -20.0),
            (0.9, -30.0),
            (0.9, -10.0),
            (0.85, -40.0),
            (0.8, -25.0),
        ],
        now_iso=fresh,
    )
    bad_rows = [(f"b{r[0]}", *r[1:]) for r in bad_rows]
    _seed_trades(tmp_db, rows + bad_rows)
    tracker = BrierCalibrationTracker(db_path=str(tmp_db), min_trades=5)
    rolling = tracker.compute_rolling_brier(["technical", "news"])
    assert rolling is not None
    # Mean of ~0.02 (technical) and ~0.81 (news) lands mid-range.
    assert 0.30 < rolling < 0.50, f"Expected mid-range mean, got {rolling}"


def test_describe_reports_per_agent_brier(tmp_db):
    rows = _mk_rows(
        0,
        [
            (0.9, 50.0),
            (0.9, 40.0),
            (-0.9, -30.0),
            (-0.9, -60.0),
            (0.8, 20.0),
            (0.8, 45.0),
        ],
    )
    _seed_trades(tmp_db, rows)
    tracker = BrierCalibrationTracker(db_path=str(tmp_db), min_trades=5)
    snapshot = tracker.describe()
    assert "briers" in snapshot
    assert "weights" in snapshot
    assert "technical" in snapshot["briers"]
    assert snapshot["db_exists"] is True
