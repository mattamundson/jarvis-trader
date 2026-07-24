"""Regression: macro_regime staleness guard tightened from 10 to 5 days (2026-07-09).

macro_regime.compute_macro_regime is an ADVISORY-only signal (never a mechanical
trade gate, never routes capital -- see backtest/macro_regime.py module docstring)
consumed by the futures pipeline as an LLM context feature. A stale weekly/monthly
SPY read should fail closed to UNKNOWN rather than advise on days-old data.

These tests fake out the three dynamic imports inside _compute() (spy_paper_track_lib,
generate_supertrend_signals, generate_sma12_momentum_signals) via sys.modules so the
staleness branch can be exercised deterministically without real SPY cache data.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from backtest import macro_regime


def _make_daily_df(days_old: int, n_rows: int = 400) -> pd.DataFrame:
    """Daily OHLC frame whose last row is `days_old` days before now."""
    end = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_old)
    idx = pd.date_range(end=end, periods=n_rows, freq="D")
    close = pd.Series(range(n_rows), index=idx, dtype=float) + 5000.0
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close}, index=idx
    )


def _install_fake_deps(monkeypatch, days_old: int, wk_up: bool, mo_up: bool) -> None:
    daily = _make_daily_df(days_old)

    fake_lib = types.ModuleType("spy_paper_track_lib")
    fake_lib._load_spy_daily = lambda: daily
    monkeypatch.setitem(sys.modules, "spy_paper_track_lib", fake_lib)

    fake_st_mod = types.ModuleType("generate_supertrend_signals")

    def _fake_supertrend(df, atr_period=10, multiplier=3.0):
        return pd.DataFrame({"trend": [1 if wk_up else -1] * len(df)}, index=df.index)

    fake_st_mod.generate_supertrend_signals = _fake_supertrend
    monkeypatch.setitem(sys.modules, "generate_supertrend_signals", fake_st_mod)

    fake_mm_mod = types.ModuleType("generate_sma12_momentum_signals")

    def _fake_momentum(df, sma_len=12):
        return pd.DataFrame({"position": [1 if mo_up else -1] * len(df)}, index=df.index)

    fake_mm_mod.generate_sma12_momentum_signals = _fake_momentum
    monkeypatch.setitem(sys.modules, "generate_sma12_momentum_signals", fake_mm_mod)


class TestMacroStalenessGuard:
    def test_fresh_data_computes_risk_on(self, monkeypatch):
        _install_fake_deps(monkeypatch, days_old=1, wk_up=True, mo_up=True)
        result = macro_regime._compute()
        assert result["state"] == "RISK_ON"
        assert result["stale_days"] <= 1

    def test_5_days_stale_boundary_still_computes(self, monkeypatch):
        """Exactly 5 days is NOT > 5, so the regime still computes (boundary is
        strict-greater-than, not >=)."""
        _install_fake_deps(monkeypatch, days_old=5, wk_up=False, mo_up=False)
        result = macro_regime._compute()
        assert result["state"] == "RISK_OFF"

    def test_6_days_stale_is_unknown_after_tightening(self, monkeypatch):
        """2026-07-09: threshold tightened 10 -> 5 days. A 6-day-old bar must
        now be UNKNOWN even though it would have passed under the old 10-day
        threshold (fail-safe: don't advise the pipeline on stale macro data)."""
        _install_fake_deps(monkeypatch, days_old=6, wk_up=True, mo_up=True)
        result = macro_regime._compute()
        assert result["state"] == "UNKNOWN"

    def test_9_days_stale_previously_valid_now_unknown(self, monkeypatch):
        """Under the old >10 threshold this would have computed a live regime;
        under the new >5 threshold it must be UNKNOWN."""
        _install_fake_deps(monkeypatch, days_old=9, wk_up=True, mo_up=False)
        result = macro_regime._compute()
        assert result["state"] == "UNKNOWN"

    def test_11_days_stale_is_unknown(self, monkeypatch):
        """Still trips under the old threshold too -- not a regression, just
        confirms the branch is reachable at the far end."""
        _install_fake_deps(monkeypatch, days_old=11, wk_up=True, mo_up=True)
        result = macro_regime._compute()
        assert result["state"] == "UNKNOWN"
