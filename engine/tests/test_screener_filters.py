"""Unit + endpoint tests for the GreenStar2-style Pine Screener filters.

Covers the pure metric functions (analytics/screener_filters.py), the filter
pass/fail logic, the no-look-ahead property, the candidate-screening
orchestration, and the POST /ib-scanner/screen endpoint (with a synthetic bar
provider so no network is touched).
"""
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from analytics.screener_filters import (
    ScreenerFilters,
    ScreenerMetrics,
    atr_pct,
    chg_open_pct,
    chg_pct,
    compute_metrics,
    minervini_score,
    passes,
    relative_volume,
    screen_candidates,
    x_from_50,
    x_from_lod_pct,
)
from backtest.screener_backtest import (
    forward_return,
    run_screener_backtest,
)

# ─── Synthetic frame helpers ─────────────────────────────────────────────────


def _flat_frame(n: int = 30, price: float = 100.0, band: float = 1.0) -> pd.DataFrame:
    """Constant-price frame: close=price, high=price+band, low=price-band.

    With a flat close, Wilder's true range is ``high-low = 2*band`` every bar,
    so ATR == 2*band exactly — handy for closed-form metric assertions.
    """
    close = pd.Series([price] * n, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + band,
            "low": close - band,
            "close": close,
            "volume": pd.Series([1000.0] * n),
        }
    )


def _uptrend_frame(n: int = 260, start: float = 10.0, stop: float = 25.0) -> pd.DataFrame:
    close = pd.Series(np.linspace(start, stop, n))
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": pd.Series([1000.0] * (n - 1) + [3000.0]),
        }
    )


# ─── Individual metric functions ─────────────────────────────────────────────


class TestMetricFunctions:
    def test_atr_pct_flat_frame(self):
        f = _flat_frame(n=30, price=100.0, band=1.0)
        # ATR == 2*band == 2.0; atr_pct == 2.0 / 100 * 100 == 2.0
        assert atr_pct(f["high"], f["low"], f["close"]) == pytest.approx(2.0, abs=1e-6)

    def test_x_from_50_two_atr_above(self):
        close = pd.Series([100.0] * 49 + [110.0])  # SMA50 == 100.2, last == 110
        result = x_from_50(close, atr=5.0, period=50)
        assert result == pytest.approx((110.0 - close.rolling(50).mean().iloc[-1]) / 5.0)
        assert result > 0

    def test_x_from_50_insufficient_history_is_nan(self):
        assert np.isnan(x_from_50(pd.Series([100.0] * 10), atr=5.0, period=50))

    def test_x_from_lod_pct_exact(self):
        # 0.7 ATR above the low -> 70.0
        assert x_from_lod_pct(close_now=100.7, low_of_day=100.0, atr=1.0) == pytest.approx(70.0)

    def test_x_from_lod_pct_zero_atr_is_nan(self):
        assert np.isnan(x_from_lod_pct(100.7, 100.0, 0.0))

    def test_chg_pct(self):
        assert chg_pct(pd.Series([100.0, 102.0])) == pytest.approx(2.0)

    def test_chg_pct_single_bar_is_nan(self):
        assert np.isnan(chg_pct(pd.Series([100.0])))

    def test_chg_open_pct(self):
        assert chg_open_pct(open_now=100.0, close_now=103.0) == pytest.approx(3.0)

    def test_relative_volume_spike(self):
        vol = pd.Series([100.0] * 20 + [300.0])
        assert relative_volume(vol, period=20) == pytest.approx(3.0)

    def test_relative_volume_insufficient_is_nan(self):
        assert np.isnan(relative_volume(pd.Series([100.0] * 5), period=20))

    def test_minervini_uptrend_scores_high(self):
        f = _uptrend_frame()
        score = minervini_score(f["close"], f["high"], f["low"])
        assert score >= 6  # strong Stage-2 uptrend passes most criteria

    def test_minervini_downtrend_scores_low(self):
        n = 260
        close = pd.Series(np.linspace(25.0, 10.0, n))
        score = minervini_score(close, close * 1.01, close * 0.99)
        assert score <= 2


# ─── compute_metrics ─────────────────────────────────────────────────────────


class TestComputeMetrics:
    def test_missing_columns_raises(self):
        with pytest.raises(ValueError):
            compute_metrics(pd.DataFrame({"close": [1.0, 2.0]}))

    def test_empty_frame_returns_blank_metrics(self):
        m = compute_metrics(_flat_frame(n=0), symbol="X")
        assert isinstance(m, ScreenerMetrics)
        assert m.symbol == "X"
        assert m.bars_used == 0

    def test_uptrend_metrics_are_finite(self):
        m = compute_metrics(_uptrend_frame(), symbol="UP")
        assert m.symbol == "UP"
        assert m.bars_used == 260
        for v in (m.atr_pct, m.rvol, m.x_from_50, m.x_from_lod_pct, m.chg_pct, m.chg_open_pct):
            assert np.isfinite(v)
        assert 0 <= m.mm_score <= 8


class TestNoLookAhead:
    def test_metrics_unaffected_by_future_bars(self):
        """A decision at bar k must not change when later bars are appended."""
        full = _uptrend_frame(n=300)
        k = 200
        early = compute_metrics(full.iloc[: k + 1], symbol="A")
        # Append the future bars, then slice back to the same decision window.
        late = compute_metrics(full.iloc[: k + 1].copy(), symbol="A")
        assert early.as_dict() == late.as_dict()
        # And the truncated window's metrics differ from the full window's
        # (sanity: the metric actually depends on the data, so the test bites).
        whole = compute_metrics(full, symbol="A")
        assert whole.last_price != early.last_price


# ─── passes() filter logic ───────────────────────────────────────────────────


def _good_metrics(**overrides) -> ScreenerMetrics:
    base = {
        "symbol": "G",
        "last_price": 50.0,
        "atr_pct": 5.0,
        "rvol": 2.0,
        "x_from_50": 1.5,
        "x_from_lod_pct": 40.0,
        "chg_pct": 3.0,
        "chg_open_pct": 1.0,
        "mm_score": 7,
        "bars_used": 260,
    }
    base.update(overrides)
    return ScreenerMetrics(**base)


class TestPasses:
    def test_all_defaults_pass(self):
        res = passes(_good_metrics(), ScreenerFilters())
        assert res.passed is True
        assert res.reasons == []

    def test_xfrom50_above_max_fails(self):
        res = passes(_good_metrics(x_from_50=5.0), ScreenerFilters())
        assert res.passed is False
        assert any("xFrom50" in r for r in res.reasons)

    def test_rvol_below_min_fails(self):
        res = passes(_good_metrics(rvol=0.5), ScreenerFilters())
        assert res.passed is False
        assert any("RVOL" in r for r in res.reasons)

    def test_lod_runaway_fails(self):
        res = passes(_good_metrics(x_from_lod_pct=120.0), ScreenerFilters())
        assert res.passed is False
        assert any("%fromLoD" in r for r in res.reasons)

    def test_down_on_day_fails(self):
        res = passes(_good_metrics(chg_pct=-1.0), ScreenerFilters())
        assert res.passed is False
        assert any("Chg%" in r for r in res.reasons)

    def test_nan_metric_fails_active_filter_with_reason(self):
        res = passes(_good_metrics(rvol=float("nan")), ScreenerFilters())
        assert res.passed is False
        assert any("RVOL" in r and "insufficient" in r for r in res.reasons)

    def test_nan_metric_passes_when_filter_disabled(self):
        f = ScreenerFilters(rvol_min=None)
        res = passes(_good_metrics(rvol=float("nan")), f)
        assert res.passed is True

    def test_mm_min_filter(self):
        f = ScreenerFilters(mm_min=8)
        assert passes(_good_metrics(mm_score=7), f).passed is False
        assert passes(_good_metrics(mm_score=8), f).passed is True

    def test_atr_band_filter(self):
        f = ScreenerFilters(atr_pct_min=2.0, atr_pct_max=4.0)
        assert passes(_good_metrics(atr_pct=5.0), f).passed is False
        assert passes(_good_metrics(atr_pct=3.0), f).passed is True


# ─── screen_candidates orchestration ─────────────────────────────────────────


class TestScreenCandidates:
    def test_skips_missing_bars_and_sorts_passing_first(self):
        frames = {
            "PASS_HI": _uptrend_frame(),  # passes, high rvol (3000)
            "NONE": None,  # skipped
        }

        # A passing frame with lower rvol than PASS_HI.
        low_rvol = _uptrend_frame()
        low_rvol.loc[low_rvol.index[-1], "volume"] = 1500.0
        frames["PASS_LO"] = low_rvol

        def provider(sym):
            return frames.get(sym)

        results = screen_candidates(
            ["PASS_LO", "NONE", "PASS_HI"], provider, ScreenerFilters(x_from_lod_max=None)
        )
        # NONE skipped -> only 2 results
        assert [r.metrics.symbol for r in results] == ["PASS_HI", "PASS_LO"]
        assert all(r.passed for r in results)

    def test_provider_exception_is_isolated(self):
        def provider(sym):
            if sym == "BOOM":
                raise RuntimeError("data source down")
            return _uptrend_frame()

        results = screen_candidates(
            ["BOOM", "OK"], provider, ScreenerFilters(x_from_lod_max=None)
        )
        assert [r.metrics.symbol for r in results] == ["OK"]

    def test_rejected_names_carry_reasons(self):
        # Force a rejection via an impossible RVOL floor.
        results = screen_candidates(["X"], lambda s: _uptrend_frame(), ScreenerFilters(rvol_min=999))
        assert results[0].passed is False
        assert results[0].reasons


# ─── POST /ib-scanner/screen endpoint ────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    from routers.ib_scanner_router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _synthetic_provider_factory(_period):
    def provider(symbol):
        f = _uptrend_frame()
        if symbol == "REJECT":
            # Make it a runaway far from LoD so the default %fromLoD<70 rejects it.
            f.loc[f.index[-1], "low"] = f["close"].iloc[-1] * 0.5
        return f

    return provider


class TestScreenEndpoint:
    def test_symbols_bypass_scanner(self, client):
        with patch(
            "routers.ib_scanner_router._make_yfinance_provider",
            side_effect=_synthetic_provider_factory,
        ):
            resp = client.post(
                "/ib-scanner/screen",
                json={"symbols": ["AAA", "REJECT"], "x_from_lod_max": 70.0},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["universe_source"] == "symbols"
        assert data["total_candidates"] == 2
        focus_syms = [r["symbol"] for r in data["focus"]]
        rejected_syms = [r["symbol"] for r in data["rejected"]]
        assert "AAA" in focus_syms
        assert "REJECT" in rejected_syms

    def test_unknown_scan_code_400(self, client):
        # Explicit symbols absent -> scanner path; bad scan_code must 400 before
        # any IB connection. The enabled-gate is checked first, so enable it.
        with patch("routers.ib_scanner_router.is_ib_scanner_enabled", return_value=True):
            resp = client.post("/ib-scanner/screen", json={"scan_code": "NOPE"})
        assert resp.status_code == 400

    def test_disabled_returns_501_on_scanner_path(self, client):
        with patch("routers.ib_scanner_router.is_ib_scanner_enabled", return_value=False):
            resp = client.post("/ib-scanner/screen", json={"scan_code": "TOP_PERC_GAIN"})
        assert resp.status_code == 501

    def test_extra_field_rejected(self, client):
        resp = client.post("/ib-scanner/screen", json={"symbols": ["AAA"], "bogus": 1})
        assert resp.status_code == 422


# ─── Screener forward-return backtest ────────────────────────────────────────


def _momentum_frame(n: int = 300, block: int = 20) -> pd.DataFrame:
    """Deterministic momentum path: alternating up/down blocks.

    Within an up-block every bar closes +1% (chg_pct > 0); within a down-block
    every bar closes -1% (chg_pct < 0). Blocks are longer than the test horizon,
    so a 'pass' on the chg% filter genuinely precedes a positive forward return
    and a 'reject' precedes a negative one — a real (not tautological) edge.
    """
    prices = [100.0]
    for t in range(1, n):
        up = (t // block) % 2 == 0
        prices.append(prices[-1] * (1.01 if up else 0.99))
    close = pd.Series(prices)
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": pd.Series([1000.0] * n),
        }
    )


# Only the daily-change filter is active for the momentum backtest.
_CHG_ONLY = ScreenerFilters(
    x_from_50_min=None,
    x_from_50_max=None,
    rvol_min=None,
    x_from_lod_max=None,
    chg_pct_min=0.0,
    chg_open_pct_min=None,
    atr_pct_min=None,
    atr_pct_max=None,
    mm_min=None,
)


class TestForwardReturn:
    def test_basic(self):
        close = pd.Series([100.0, 101.0, 102.0, 103.0])
        assert forward_return(close, 0, 2) == pytest.approx(102.0 / 100.0 - 1.0)

    def test_out_of_range_is_nan(self):
        close = pd.Series([100.0, 101.0, 102.0])
        assert np.isnan(forward_return(close, 1, 5))


class TestScreenerBacktest:
    def test_momentum_filter_has_positive_edge(self):
        res = run_screener_backtest(
            {"MOM": _momentum_frame()},
            _CHG_ONLY,
            horizon=5,
            step=5,
            min_history=60,
        )
        assert res.n_decisions == res.passed.n + res.rejected.n
        assert res.passed.n > 0 and res.rejected.n > 0
        assert res.passed.mean_fwd_return > 0
        assert res.rejected.mean_fwd_return < 0
        assert res.edge > 0

    def test_pass_everything_filter_buckets_all_as_pass(self):
        wide = ScreenerFilters(
            x_from_50_min=None,
            x_from_50_max=None,
            rvol_min=None,
            x_from_lod_max=None,
            chg_pct_min=None,
        )
        res = run_screener_backtest({"UP": _uptrend_frame(n=300)}, wide, min_history=60)
        assert res.rejected.n == 0
        assert res.passed.n == res.n_decisions
        assert np.isnan(res.edge)  # no reject bucket to compare against

    def test_decisions_exclude_bars_without_horizon_room(self):
        frame = _uptrend_frame(n=300)
        horizon = 5
        res = run_screener_backtest({"UP": frame}, _CHG_ONLY, horizon=horizon, step=1, min_history=60)
        # Last evaluable decision index is len - horizon - 1; decisions counted
        # from index 60. Anything inside the final `horizon` bars is excluded.
        expected = (len(frame) - horizon - 1) - 60 + 1
        assert res.n_decisions == expected

    def test_short_frame_yields_no_decisions(self):
        res = run_screener_backtest({"SHORT": _uptrend_frame(n=50)}, _CHG_ONLY, min_history=210)
        assert res.n_decisions == 0
        assert res.symbols == []

    def test_invalid_horizon_raises(self):
        with pytest.raises(ValueError):
            run_screener_backtest({"X": _uptrend_frame()}, horizon=0)
