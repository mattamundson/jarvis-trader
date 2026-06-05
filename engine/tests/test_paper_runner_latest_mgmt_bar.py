"""Tests for paper_runner._latest_mgmt_bar feed-fallback + empty-frame guard.

_latest_mgmt_bar prefers the freshest 5m bar and falls back to the latest 1h
signal bar. The fallback previously did an unguarded .iloc[-1], so a dry 5m
feed combined with an empty 1h frame surfaced a bare IndexError far from the
cause and crashed the poll cycle. It now raises a clear ValueError.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from backtest import paper_runner
from backtest.paper_runner import _latest_mgmt_bar


def _bar_df(ts: str, close: float) -> pd.DataFrame:
    idx = pd.DatetimeIndex([pd.Timestamp(ts, tz="UTC")])
    return pd.DataFrame(
        {"open": [close], "high": [close + 1], "low": [close - 1], "close": [close]},
        index=idx,
    )


def test_prefers_latest_5m_bar(monkeypatch):
    df_5m = _bar_df("2026-06-05T14:05:00", 100.0)
    df_1h = _bar_df("2026-06-05T13:00:00", 99.0)
    monkeypatch.setattr(paper_runner, "fetch_bars", lambda *a, **k: df_5m)

    bar, ts = _latest_mgmt_bar("MES", {}, df_1h)
    assert bar["close"] == 100.0  # 5m bar won
    assert "2026-06-05 14:05" in ts


def test_falls_back_to_1h_when_5m_unavailable(monkeypatch):
    df_1h = _bar_df("2026-06-05T13:00:00", 99.0)
    monkeypatch.setattr(paper_runner, "fetch_bars", lambda *a, **k: None)

    bar, ts = _latest_mgmt_bar("MES", {}, df_1h)
    assert bar["close"] == 99.0  # fell back to 1h
    assert "2026-06-05 13:00" in ts


def test_falls_back_to_1h_when_5m_empty(monkeypatch):
    empty = pd.DataFrame()
    df_1h = _bar_df("2026-06-05T13:00:00", 99.0)
    monkeypatch.setattr(paper_runner, "fetch_bars", lambda *a, **k: empty)

    bar, _ = _latest_mgmt_bar("MES", {}, df_1h)
    assert bar["close"] == 99.0


def test_raises_clear_error_when_both_feeds_dry(monkeypatch):
    monkeypatch.setattr(paper_runner, "fetch_bars", lambda *a, **k: None)
    with pytest.raises(ValueError, match="cannot manage position"):
        _latest_mgmt_bar("MES", {}, pd.DataFrame())


def test_raises_clear_error_when_5m_empty_and_1h_empty(monkeypatch):
    monkeypatch.setattr(paper_runner, "fetch_bars", lambda *a, **k: pd.DataFrame())
    with pytest.raises(ValueError, match="no 5m feed and empty 1h frame"):
        _latest_mgmt_bar("MES", {}, pd.DataFrame())
