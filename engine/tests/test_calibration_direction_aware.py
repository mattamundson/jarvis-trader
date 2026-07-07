"""
Direction-aware calibration regression tests.

Bug (2026-06-16): IC (Spearman of signal vs realized return) and the Brier
correctness label both used raw ``pnl_usd``, which is inverted for SHORT
trades -- so a bullish analyst whose call was right (price rose) but whose
executed SHORT lost money was scored "confidently wrong". This pushed the
rolling Brier worse than the 0.25 coin-flip baseline and corrupted IC-based
agent weights. Fixed by ``_directional_return`` (flip pnl sign on SHORT so
both metrics measure the analyst against the realized PRICE direction).
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from analytics.ic_ensemble import (  # noqa: E402
    BrierCalibrationTracker,
    ICWeightedEnsemble,
    _directional_return,
)


def _make_db(path, rows):
    """rows: list of (offset_seconds, direction, pnl_usd, technical_signal)."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        """CREATE TABLE trade_outcomes (
            trade_id TEXT, timestamp TEXT, symbol TEXT, direction TEXT,
            pnl_usd REAL, pnl_pct REAL, outcome TEXT, technical_signal REAL
        )"""
    )
    base = datetime.now(timezone.utc)
    for i, (off, direction, pnl, sig) in enumerate(rows):
        ts = (base - timedelta(seconds=off)).isoformat()
        conn.execute(
            "INSERT INTO trade_outcomes "
            "(trade_id, timestamp, symbol, direction, pnl_usd, technical_signal) "
            "VALUES (?,?,?,?,?,?)",
            (f"t{i}", ts, "MES", direction, pnl, sig),
        )
    conn.commit()
    conn.close()


class TestDirectionalReturnHelper:
    def test_long_passthrough(self):
        assert _directional_return(100.0, "LONG") == 100.0
        assert _directional_return(-50.0, "LONG") == -50.0

    def test_short_flips_sign(self):
        assert _directional_return(100.0, "SHORT") == -100.0
        assert _directional_return(-100.0, "short") == 100.0  # case-insensitive

    def test_unknown_direction_passthrough(self):
        assert _directional_return(100.0, None) == 100.0
        assert _directional_return(100.0, "") == 100.0


class TestBrierDirectionAware:
    def test_short_correct_calls_are_credited(self, tmp_path):
        # 5 closed trades for one analyst. Rows 2 and 3 are SHORT trades where
        # the analyst's directional call was RIGHT even though the trade's pnl
        # sign (executed side) differs.
        rows = [
            (50, "LONG", +100.0, +0.9),   # price up, bullish     -> correct
            (40, "SHORT", -100.0, +0.9),  # SHORT loss => price up, bullish  -> correct (was scored wrong)
            (30, "SHORT", +100.0, -0.9),  # SHORT win  => price dn, bearish  -> correct (was scored wrong)
            (20, "SHORT", +100.0, +0.9),  # SHORT win  => price dn, bullish  -> WRONG
            (10, "LONG", -100.0, -0.9),   # price down, bearish   -> correct
        ]
        db = tmp_path / "fb.db"
        _make_db(db, rows)
        tracker = BrierCalibrationTracker(db_path=str(db), agents=["technical"], min_trades=1)

        brier = tracker.compute_brier("technical")
        # 4 correct @ conf 0.9 -> (0.9-1)^2 = 0.01 each; 1 wrong -> (0.9-0)^2 = 0.81
        assert brier == pytest.approx((0.01 * 4 + 0.81) / 5, abs=1e-6)  # 0.17
        # The pre-fix raw-pnl formula would have scored this 0.33 (worse than coin-flip).
        assert brier < 0.25

    def test_rolling_brier_matches(self, tmp_path):
        rows = [
            (50, "LONG", +100.0, +0.9),
            (40, "SHORT", -100.0, +0.9),
            (30, "SHORT", +100.0, -0.9),
            (20, "SHORT", +100.0, +0.9),
            (10, "LONG", -100.0, -0.9),
        ]
        db = tmp_path / "fb.db"
        _make_db(db, rows)
        tracker = BrierCalibrationTracker(db_path=str(db), agents=["technical"], min_trades=1)
        assert tracker.compute_rolling_brier() == pytest.approx(0.17, abs=1e-6)


class TestICDirectionAware:
    def test_ic_positive_when_signal_tracks_price_direction(self, tmp_path):
        # Signal sign matches the realized price direction on every row,
        # including the SHORT rows -> perfect rank alignment -> IC ~ 1.0.
        rows = [
            (50, "LONG", +200.0, +0.8),   # price up,   bullish
            (40, "LONG", +100.0, +0.4),   # price up,   mildly bullish
            (30, "SHORT", -150.0, +0.6),  # SHORT loss => price up, bullish
            (20, "SHORT", +120.0, -0.5),  # SHORT win  => price dn, bearish
            (10, "LONG", -180.0, -0.7),   # price down, bearish
        ]
        db = tmp_path / "fb.db"
        _make_db(db, rows)
        ens = ICWeightedEnsemble(db_path=str(db), agents=["technical"], min_trades=1)
        assert ens.compute_ic("technical") > 0.9
