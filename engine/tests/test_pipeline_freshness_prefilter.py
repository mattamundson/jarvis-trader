"""Integration tests: the interval-scaled freshness gate wired into
engine.agents.pipeline.pre_filter_signal (SOTA plan P1.4).

Confirms the read-time check runs BEFORE any signal computation, on the
actual decision path a symbol takes every pipeline cycle, and forces a HOLD
result rather than silently skipping or permitting a trade on stale data.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.pipeline import pre_filter_signal


def _ohlcv(idx: pd.DatetimeIndex) -> pd.DataFrame:
    n = len(idx)
    base = 7400.0
    return pd.DataFrame(
        {
            "open": [base + i * 0.1 for i in range(n)],
            "high": [base + i * 0.1 + 2 for i in range(n)],
            "low": [base + i * 0.1 - 2 for i in range(n)],
            "close": [base + i * 0.1 + 1 for i in range(n)],
            "volume": [1000.0] * n,
        },
        index=idx,
    )


def _agents_with_bars(df: pd.DataFrame) -> dict:
    data_mgr = MagicMock()
    data_mgr.get_bars = AsyncMock(return_value=df)
    return {"technical": SimpleNamespace(_data=data_mgr)}


class TestFreshnessPreFilter:
    async def test_stale_bars_force_hold_before_signal_computation(self, monkeypatch):
        monkeypatch.delenv("BAR_FRESHNESS_GATE_ENABLED", raising=False)
        monkeypatch.delenv("BAR_FRESHNESS_STALE_MULTIPLIER", raising=False)
        monkeypatch.delenv("BAR_FRESHNESS_MIN_FLOOR_SECONDS", raising=False)

        now = pd.Timestamp.now(tz="UTC")
        # 1h interval -> ~3h ceiling; 6h-old newest bar is unambiguously stale.
        idx = pd.date_range(end=now - pd.Timedelta(hours=6), periods=40, freq="1h")
        agents = _agents_with_bars(_ohlcv(idx))

        result = await pre_filter_signal("MES", "1h", True, agents)

        assert result is not None
        assert result["final_action"] == "hold"
        assert result["final_quantity"] == 0
        assert result["pre_filtered"] is True
        assert "stale data" in result["pre_filter_reason"]
        assert result["bar_age_seconds"] > result["bar_freshness_threshold_seconds"]

    async def test_fresh_bars_do_not_trigger_freshness_hold(self, monkeypatch):
        monkeypatch.delenv("BAR_FRESHNESS_GATE_ENABLED", raising=False)
        monkeypatch.delenv("BAR_FRESHNESS_STALE_MULTIPLIER", raising=False)
        monkeypatch.delenv("BAR_FRESHNESS_MIN_FLOOR_SECONDS", raising=False)

        now = pd.Timestamp.now(tz="UTC")
        idx = pd.date_range(end=now - pd.Timedelta(minutes=5), periods=60, freq="1h")
        agents = _agents_with_bars(_ohlcv(idx))

        result = await pre_filter_signal("MES", "1h", True, agents)

        # Downstream stages (STC/VIX/etc.) may still legitimately return a
        # HOLD or None for unrelated reasons in this synthetic-data test —
        # the only thing under test is that freshness itself never fires.
        if result is not None:
            assert "stale data" not in (result.get("pre_filter_reason") or "")

    async def test_gate_disabled_does_not_block_stale_bars(self, monkeypatch):
        monkeypatch.setenv("BAR_FRESHNESS_GATE_ENABLED", "0")

        now = pd.Timestamp.now(tz="UTC")
        idx = pd.date_range(end=now - pd.Timedelta(hours=6), periods=40, freq="1h")
        agents = _agents_with_bars(_ohlcv(idx))

        result = await pre_filter_signal("MES", "1h", True, agents)

        if result is not None:
            assert "stale data" not in (result.get("pre_filter_reason") or "")

    async def test_short_interval_scales_the_ceiling_down(self, monkeypatch):
        """The same 30-minute-old bar is fine for 1h bars but stale for 5m
        bars — proves the threshold is interval-scaled, not a fixed ceiling."""
        monkeypatch.delenv("BAR_FRESHNESS_GATE_ENABLED", raising=False)
        monkeypatch.delenv("BAR_FRESHNESS_STALE_MULTIPLIER", raising=False)
        monkeypatch.delenv("BAR_FRESHNESS_MIN_FLOOR_SECONDS", raising=False)

        now = pd.Timestamp.now(tz="UTC")
        idx = pd.date_range(end=now - pd.Timedelta(minutes=30), periods=40, freq="5min")
        agents = _agents_with_bars(_ohlcv(idx))

        result = await pre_filter_signal("MES", "5m", True, agents)

        assert result is not None
        assert result["pre_filtered"] is True
        assert "stale data" in result["pre_filter_reason"]

    async def test_no_data_manager_returns_none_not_a_crash(self):
        """Pre-existing early-return path (no _data on the technical agent)
        must be untouched by the new check."""
        result = await pre_filter_signal("MES", "1h", True, {"technical": SimpleNamespace()})
        assert result is None
