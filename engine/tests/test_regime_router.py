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


# ── /regime/vix-percentile: n_vix_bars must honestly reflect the lookback label ──
# GT-22 (2026-07-27): the live endpoint returned n_vix_bars=21 while labeling the
# snapshot lookback=252 (momentum_window=63) — a full year's worth of percentile
# math computed off ~one month of data. Root cause was in the IBKR duration_map
# (data/market_data.py), not here, but this asserts the contract this router
# promises callers: when enough calendar history is available, n_vix_bars must be
# large enough to actually support the claimed lookback/momentum_window, not stop
# two orders of magnitude short of it.


def _daily_df(n: int, start: str = "2023-01-02") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=n)
    close = pd.Series(np.linspace(10.0, 30.0, n), index=idx)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(n, 1_000.0),
        },
        index=idx,
    )


class _FakeVixDataManager:
    """Stands in for MarketDataManager.get_bars, returning a bar count that
    depends on the symbol -- mimics a healthy fetch layer that actually honors
    the requested lookback (contrast with the pre-fix IBKR duration_map bug,
    which silently truncated every long-window request to ~21 daily bars
    regardless of what was asked for)."""

    def __init__(self, n_bars: int):
        self._n_bars = n_bars
        self.requested_lookback_days: list[int] = []

    async def get_bars(self, symbol, lookback_days, timeframe):
        self.requested_lookback_days.append(lookback_days)
        return _daily_df(self._n_bars)


async def test_vix_percentile_n_bars_consistent_with_lookback_label(monkeypatch):
    """When the fetch layer honors the request, n_vix_bars must be large enough
    to actually back a lookback=252/momentum_window=63 label -- not the ~21-bar
    (one month) shortfall GT-22 found live. 300 bars comfortably covers
    252 + 63 with the endpoint's own 1.6x calendar buffer."""
    fake_dm = _FakeVixDataManager(n_bars=300)
    monkeypatch.setattr(regime_router, "data_manager", fake_dm)

    result = await regime_router.get_vix_percentile_regime()

    assert result["lookback"] == 252
    assert result["momentum_window"] == 63
    # The core GT-22 assertion: n_vix_bars must be commensurate with the claimed
    # 252-day lookback (at least the lookback itself), never a ~21-bar (1-month)
    # shortfall dressed up with a 252-day label.
    assert result["n_vix_bars"] >= 252, (
        f"n_vix_bars={result['n_vix_bars']} is far short of the labeled "
        f"lookback={result['lookback']} — dishonest label (GT-22 regression)"
    )
    # And the router must actually have asked the fetch layer for a window sized
    # to the lookback + momentum_window it claims, not something ~1-month-sized.
    assert all(d >= 252 for d in fake_dm.requested_lookback_days)


async def test_vix_percentile_n_bars_matches_true_available_window(monkeypatch):
    """If genuinely fewer bars are available than the label implies, n_vix_bars
    must reflect that true (smaller) count rather than lying upward -- the
    'honest label' half of the GT-22 fix criteria."""
    fake_dm = _FakeVixDataManager(n_bars=40)
    monkeypatch.setattr(regime_router, "data_manager", fake_dm)

    result = await regime_router.get_vix_percentile_regime()

    assert result["n_vix_bars"] == 40
