"""The backtest data loader must screen contaminated bars before returning.

Guards the gap where backtests read the CSV cache directly and bypassed the
write-time bar-quality gate (which only covered the live bars repository).
"""

from __future__ import annotations

import pandas as pd

from backtest.data_loader import BacktestDataLoader


def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df["timestamp"])
    return df


def test_screen_drops_impossible_and_explosion_bars(monkeypatch):
    monkeypatch.setenv("BAR_QUALITY_GATE_ENABLED", "1")
    loader = BacktestDataLoader()

    df = _frame(
        [
            {"timestamp": "2026-01-01 09:30", "open": 5000, "high": 5010, "low": 4995, "close": 5005, "volume": 100},
            # impossible: high < low
            {"timestamp": "2026-01-01 09:31", "open": 5005, "high": 4990, "low": 5008, "close": 5006, "volume": 90},
            {"timestamp": "2026-01-01 09:32", "open": 5006, "high": 5012, "low": 5001, "close": 5009, "volume": 80},
            # range explosion: (high-low)/low huge (contamination class)
            {"timestamp": "2026-01-01 09:33", "open": 5009, "high": 99999, "low": 5000, "close": 5010, "volume": 70},
        ]
    )

    out = loader._screen_bar_quality(df, "ES", "1m")
    assert len(out) == 2, f"expected 2 clean bars, got {len(out)}"
    assert out["high"].ge(out["low"]).all()


def test_screen_keeps_clean_frame(monkeypatch):
    monkeypatch.setenv("BAR_QUALITY_GATE_ENABLED", "1")
    loader = BacktestDataLoader()
    df = _frame(
        [
            {"timestamp": "2026-01-01 09:30", "open": 5000, "high": 5010, "low": 4995, "close": 5005, "volume": 100},
            {"timestamp": "2026-01-01 09:31", "open": 5005, "high": 5015, "low": 5002, "close": 5012, "volume": 90},
        ]
    )
    out = loader._screen_bar_quality(df, "ES", "1m")
    assert len(out) == 2


def test_screen_respects_kill_switch(monkeypatch):
    monkeypatch.setenv("BAR_QUALITY_GATE_ENABLED", "0")
    loader = BacktestDataLoader()
    df = _frame(
        [
            {"timestamp": "2026-01-01 09:30", "open": 5000, "high": 4990, "low": 5008, "close": 5005, "volume": 100},
        ]
    )
    out = loader._screen_bar_quality(df, "ES", "1m")
    assert len(out) == 1  # gate disabled -> nothing dropped
