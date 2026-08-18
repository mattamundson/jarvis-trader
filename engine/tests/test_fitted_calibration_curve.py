"""
Tests -- fitted isotonic signal->probability calibration curve (MR-1.1, 2nd half).

MR-1.1's proof line has two halves: (1) the scoring rule must be proper
[DONE, commit 890ad09] and (2) it should be "a real signal->probability
calibration map (monotonic curve fit on realized outcomes)" rather than the
linear map score_forecast() still uses. This covers the new fitted-curve
capability (analytics/calibration.py + BrierCalibrationTracker.
fit_current_calibration_curve).

The most important test here is test_live_wired_methods_unchanged: this
capability must be purely additive. Fitting a curve on a window and using it
to rescore that same window would be in-sample (point-in-time violation, see
.claude/rules/testing.md) and would corrupt the one field
(/health.brier_30d_rolling) the real-money-readiness gate actually reads --
so compute_brier/compute_rolling_brier/get_calibration_weights must be
byte-identical before and after this change.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from analytics.calibration import MIN_SAMPLES_FOR_CALIBRATION_FIT, fit_isotonic_calibration
from analytics.ic_ensemble import BrierCalibrationTracker

pytest.importorskip("sklearn", reason="isotonic calibration requires sklearn")


# --- fit_isotonic_calibration (pure function) -------------------------------


def test_returns_none_below_min_samples():
    pairs = [(0.9, 50.0)] * (MIN_SAMPLES_FOR_CALIBRATION_FIT - 1)
    assert fit_isotonic_calibration(pairs) is None


def test_returns_none_on_degenerate_all_same_outcome():
    # Every trade wins regardless of signal -- nothing to fit against.
    pairs = [(s, 10.0) for s in [-0.9, -0.5, 0.0, 0.3, 0.8, 0.9, -0.2, 0.4, 0.1, -0.7, 0.6, 0.2, -0.3, 0.5, 0.7]]
    assert fit_isotonic_calibration(pairs) is None


def test_monotonic_nondecreasing_over_signal_range():
    # Clearly separable synthetic data: negative signal -> mostly losses,
    # positive signal -> mostly wins.
    pairs = []
    for _ in range(10):
        pairs.append((-0.8, -20.0))
        pairs.append((0.8, 20.0))
    pairs.append((0.0, 5.0))
    pairs.append((0.0, -5.0))
    curve = fit_isotonic_calibration(pairs)
    assert curve is not None

    probs = [curve(s) for s in (-1.0, -0.5, 0.0, 0.5, 1.0)]
    assert all(0.0 <= p <= 1.0 for p in probs)
    assert probs == sorted(probs)  # non-decreasing


def test_output_clipped_to_unit_interval_for_out_of_range_input():
    pairs = [(-0.8, -20.0), (0.8, 20.0)] * 10
    curve = fit_isotonic_calibration(pairs)
    assert curve is not None
    assert 0.0 <= curve(5.0) <= 1.0
    assert 0.0 <= curve(-5.0) <= 1.0


def test_fitted_curve_beats_linear_map_on_separable_data():
    """The docstring's own claim ('a fitted map would be strictly better') --
    pin it: on data where the TRUE relationship is nonlinear/saturating, the
    isotonic fit's calibration error against true frequency should be no
    worse than the naive linear map's."""
    # Signal saturates early: anything >=0.3 wins ~90% of the time, anything
    # <=-0.3 loses ~90% of the time, near-zero is a coinflip. A linear map
    # mis-calibrates the saturated region; isotonic should track it better.
    import random

    rng = random.Random(42)
    pairs = []
    for _ in range(60):
        sig = rng.choice([-0.9, -0.3, 0.0, 0.3, 0.9])
        if sig >= 0.3:
            pnl = 10.0 if rng.random() < 0.9 else -10.0
        elif sig <= -0.3:
            pnl = -10.0 if rng.random() < 0.9 else 10.0
        else:
            pnl = 10.0 if rng.random() < 0.5 else -10.0
        pairs.append((sig, pnl))

    curve = fit_isotonic_calibration(pairs)
    assert curve is not None

    def linear(s):
        return (max(-1.0, min(1.0, s)) + 1.0) / 2.0

    true_p = {-0.9: 0.1, -0.3: 0.1, 0.0: 0.5, 0.3: 0.9, 0.9: 0.9}

    isotonic_err = sum((curve(s) - p) ** 2 for s, p in true_p.items())
    linear_err = sum((linear(s) - p) ** 2 for s, p in true_p.items())
    assert isotonic_err <= linear_err


# --- BrierCalibrationTracker.fit_current_calibration_curve ------------------


def _seed_trades(db_path: Path, rows):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_outcomes (
                trade_id TEXT PRIMARY KEY, timestamp TEXT, symbol TEXT, direction TEXT,
                pnl_usd REAL, pnl_pct REAL, outcome TEXT,
                technical_signal REAL, news_signal REAL, social_signal REAL,
                fundamental_signal REAL, corey_signal REAL
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


def _fresh_iso():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _mk_rows(signals_and_pnls):
    now_iso = _fresh_iso()
    rows = []
    for i, (sig, pnl) in enumerate(signals_and_pnls):
        rows.append(
            (f"t{i:03d}", now_iso, "MCL", "LONG", pnl, 0.0, "WIN" if pnl > 0 else "LOSS",
             sig, 0.0, 0.0, 0.0, 0.0)
        )
    return rows


@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "agent_feedback.db"


def test_fit_current_calibration_curve_end_to_end(tmp_db):
    # outcome_hygiene.sanitize_outcome_rows treats identical (signal, pnl)
    # repeats as suspicious duplicate outcomes and filters them -- vary pnl
    # per row like real trades would, not a batch of exact clones.
    rows = _mk_rows(
        [(0.8, 20.0 + i) for i in range(10)] + [(-0.8, -20.0 - i) for i in range(10)]
    )
    _seed_trades(tmp_db, rows)

    tracker = BrierCalibrationTracker(db_path=str(tmp_db), agents=["technical"])
    curve = tracker.fit_current_calibration_curve("technical")

    assert curve is not None
    assert curve(0.8) > curve(-0.8)


def test_fit_current_calibration_curve_none_on_missing_db(tmp_path):
    tracker = BrierCalibrationTracker(db_path=str(tmp_path / "nonexistent.db"), agents=["technical"])
    assert tracker.fit_current_calibration_curve("technical") is None


def test_live_wired_methods_unchanged(tmp_db):
    """The critical regression guard: adding fit_current_calibration_curve
    must not alter compute_brier / compute_rolling_brier / get_calibration_weights
    -- these feed the live /health.brier_30d_rolling field the real-money-
    readiness gate reads. Any drift here would be a point-in-time violation."""
    rows = _mk_rows([(0.9, 50.0), (0.8, 30.0), (-0.9, -40.0), (0.1, 10.0), (-0.2, -5.0), (0.5, 20.0)])
    _seed_trades(tmp_db, rows)

    tracker = BrierCalibrationTracker(db_path=str(tmp_db), agents=["technical", "news"])

    brier_before = tracker.compute_brier("technical")
    rolling_before = tracker.compute_rolling_brier()
    weights_before = tracker.get_calibration_weights()

    # Calling the new method must have zero side effects on the tracker.
    tracker.fit_current_calibration_curve("technical")

    assert tracker.compute_brier("technical") == brier_before
    assert tracker.compute_rolling_brier() == rolling_before
    assert tracker.get_calibration_weights() == weights_before
