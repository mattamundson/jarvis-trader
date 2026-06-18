"""Tests for the intraday market-regime scorer and endpoint.

Pure-function coverage (deterministic synthetic bars) plus a handler-level test
of GET /regime/intraday with a fake data manager. No network, no LLM.
"""

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from analytics.intraday_regime import (
    bias_from_score,
    build_history,
    build_indicators,
    build_regime_snapshot,
    direction_from_score,
    timeframe_score,
)
from routers import regime_router


def _make_df(prices: np.ndarray, freq: str = "1h") -> pd.DataFrame:
    """OHLCV frame with a DatetimeIndex from a close-price path."""
    n = len(prices)
    idx = pd.date_range("2024-06-03 09:30", periods=n, freq=freq)
    close = pd.Series(prices, index=idx)
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


@pytest.fixture
def uptrend_df() -> pd.DataFrame:
    return _make_df(np.linspace(100, 130, 160))


@pytest.fixture
def downtrend_df() -> pd.DataFrame:
    return _make_df(np.linspace(130, 100, 160))


# ── Pure scoring ──────────────────────────────────────────────────────────────

def test_uptrend_scores_bullish(uptrend_df):
    score = timeframe_score(uptrend_df)
    assert score > 25, f"steady uptrend should be strongly bullish, got {score}"


def test_downtrend_scores_bearish(downtrend_df):
    score = timeframe_score(downtrend_df)
    assert score < -25, f"steady downtrend should be strongly bearish, got {score}"


def test_score_is_bounded(uptrend_df, downtrend_df):
    assert -100 <= timeframe_score(uptrend_df) <= 100
    assert -100 <= timeframe_score(downtrend_df) <= 100


def test_empty_df_scores_zero():
    assert timeframe_score(pd.DataFrame()) == 0.0


@pytest.mark.parametrize(
    "score,expected",
    [(60, "BULLISH"), (-60, "BEARISH"), (0, "NEUTRAL"), (25, "BULLISH"), (-25, "BEARISH")],
)
def test_direction_thresholds(score, expected):
    assert direction_from_score(score) == expected


@pytest.mark.parametrize(
    "score,expected",
    [(15, "BULL"), (-15, "BEAR"), (0, "NEUTRAL"), (10, "BULL"), (-10, "BEAR")],
)
def test_bias_thresholds(score, expected):
    assert bias_from_score(score) == expected


# ── Indicator cards ───────────────────────────────────────────────────────────

def test_build_indicators_shape(uptrend_df):
    cards = build_indicators(uptrend_df)
    assert len(cards) == 10
    labels = {c["label"] for c in cards}
    assert {"VWAP", "DONCHIAN", "EMA STACK", "RSI", "MACD HIST", "BB POSITION"} <= labels
    for card in cards:
        assert set(card) >= {"label", "value", "detail", "tone", "fill"}
        assert card["tone"] in {"bull", "bear", "neutral"}
        assert 0.0 <= card["fill"] <= 1.0


def test_uptrend_indicators_lean_bull(uptrend_df):
    cards = build_indicators(uptrend_df)
    bull = sum(1 for c in cards if c["tone"] == "bull")
    bear = sum(1 for c in cards if c["tone"] == "bear")
    assert bull > bear


# ── History ───────────────────────────────────────────────────────────────────

def test_history_capped_and_shaped(uptrend_df):
    long_df = _make_df(np.linspace(100, 200, 500), freq="5min")
    hist = build_history(long_df, max_points=350)
    assert len(hist) == 350
    point = hist[0]
    assert set(point) == {"time", "score", "short_ema", "long_ema", "extra_ema"}


# ── Full snapshot ─────────────────────────────────────────────────────────────

def test_snapshot_full_shape(uptrend_df):
    bars = {"5m": uptrend_df, "15m": uptrend_df, "1h": uptrend_df}
    snap = build_regime_snapshot("spy", bars)
    assert snap["symbol"] == "SPY"
    assert snap["direction"] == "BULLISH"
    assert len(snap["timeframe_scores"]) == 3
    assert len(snap["indicators"]) == 10
    assert snap["options_flow"] is None
    assert 0.0 <= snap["direction_pct"] <= 100.0
    assert snap["conviction"] in {"HIGH", "MEDIUM", "LOW"}
    assert snap["snapshot_count"] == len(snap["history"])


def test_snapshot_blends_timeframes(uptrend_df, downtrend_df):
    # 1h (weight 0.5) bearish should pull a mixed blend below the 5m/15m read.
    bars = {"5m": uptrend_df, "15m": uptrend_df, "1h": downtrend_df}
    snap = build_regime_snapshot("SPY", bars)
    only_up = build_regime_snapshot("SPY", {"1h": uptrend_df})
    assert snap["score"] < only_up["score"]


# ── Endpoint handler ──────────────────────────────────────────────────────────

class _FakeDataManager:
    def __init__(self, df: pd.DataFrame):
        self._df = df
        self.calls: list[str] = []

    async def get_bars(self, symbol, lookback_days, timeframe, is_futures):
        self.calls.append(timeframe)
        return self._df


async def test_endpoint_returns_snapshot(uptrend_df, monkeypatch):
    monkeypatch.setattr(regime_router, "data_manager", _FakeDataManager(uptrend_df))
    result = await regime_router.get_intraday_regime(symbol="spy")
    assert result["symbol"] == "SPY"
    assert result["direction"] == "BULLISH"
    assert len(result["indicators"]) == 10


async def test_endpoint_503_without_data_manager(monkeypatch):
    monkeypatch.setattr(regime_router, "data_manager", None)
    with pytest.raises(HTTPException) as exc:
        await regime_router.get_intraday_regime(symbol="SPY")
    assert exc.value.status_code == 503


async def test_endpoint_404_when_no_bars(monkeypatch):
    class _EmptyDM:
        async def get_bars(self, *a, **k):
            return pd.DataFrame()

    monkeypatch.setattr(regime_router, "data_manager", _EmptyDM())
    with pytest.raises(HTTPException) as exc:
        await regime_router.get_intraday_regime(symbol="SPY")
    assert exc.value.status_code == 404
