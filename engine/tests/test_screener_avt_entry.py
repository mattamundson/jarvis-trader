"""Tests for the screener-gated Adaptive Volatility Trend entry rule.

Covers the single-symbol entry composition (screener AND AVT-long), the
universe orchestration, and the combined backtest (combined vs screener-only).
"""
import numpy as np
import pandas as pd
import pytest

from analytics.adaptive_volatility_trend import AVTParams
from analytics.screener_filters import ScreenerFilters
from backtest.screener_avt_entry import (
    CombinedBacktestResult,
    evaluate_entry,
    qualified_entries,
    run_combined_backtest,
)

# Loose screener + ungated AVT so tests exercise the *composition*, not the
# individual filters (those are covered in their own suites).
_LOOSE_SCREEN = ScreenerFilters(
    x_from_50_min=None, x_from_50_max=None, x_from_lod_max=None, rvol_min=1.0, chg_pct_min=0.0
)
_UNGATED_AVT = AVTParams(use_rsi_gate=False, use_volume_gate=False, min_score=0.0)


def _last_bar_cross_up_frame(n: int = 160, seed: int = 3) -> pd.DataFrame:
    """Sideways-below-trend then a final bar that crosses up on a volume spike."""
    rng = np.random.default_rng(seed)
    base = 100 + np.cumsum(rng.normal(0, 0.2, n))
    base = np.append(base, base[-1] * 1.03)
    close = pd.Series(base)
    vol = pd.Series([1000.0] * n + [4000.0])
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close * 1.001,
            "low": close * 0.999,
            "close": close,
            "volume": vol,
        }
    )


class TestEvaluateEntry:
    def test_qualified_when_screener_passes_and_avt_long(self):
        d = evaluate_entry(_last_bar_cross_up_frame(), _LOOSE_SCREEN, _UNGATED_AVT)
        assert d.screener_passed is True
        assert d.avt_long is True
        assert d.avt_signal == 1
        assert d.qualified is True

    def test_not_qualified_when_avt_score_below_floor(self):
        d = evaluate_entry(
            _last_bar_cross_up_frame(), _LOOSE_SCREEN, _UNGATED_AVT, min_avt_score=200.0
        )
        assert d.screener_passed is True  # screener still passes
        assert d.avt_long is False  # but no score can exceed 100
        assert d.qualified is False

    def test_not_qualified_when_screener_fails(self):
        d = evaluate_entry(
            _last_bar_cross_up_frame(), ScreenerFilters(rvol_min=9999), _UNGATED_AVT
        )
        assert d.screener_passed is False
        assert d.qualified is False
        assert d.screener_reasons  # carries the failing reason

    def test_qualified_implies_both_conditions(self):
        d = evaluate_entry(_last_bar_cross_up_frame(), _LOOSE_SCREEN, _UNGATED_AVT)
        assert d.qualified == (d.screener_passed and d.avt_long)


class TestQualifiedEntries:
    def test_sorts_qualified_first_and_skips_missing(self):
        frames = {
            "GOOD": _last_bar_cross_up_frame(),
            "NONE": None,
            "FAILSCREEN": _last_bar_cross_up_frame(),
        }

        def provider(sym):
            return frames.get(sym)

        # FAILSCREEN passed an impossible screener only for itself via a per-call
        # filter is not possible here, so make it fail by using a frame whose last
        # bar is flat (no cross) -> not qualified.
        flat = _last_bar_cross_up_frame()
        flat.loc[flat.index[-1], "close"] = flat["close"].iloc[-2]  # remove the cross
        flat.loc[flat.index[-1], "volume"] = 100.0  # and the volume spike
        frames["FAILSCREEN"] = flat

        out = qualified_entries(
            ["FAILSCREEN", "NONE", "GOOD"], provider, _LOOSE_SCREEN, _UNGATED_AVT
        )
        assert [d.symbol for d in out] == ["GOOD", "FAILSCREEN"]  # NONE skipped
        assert out[0].qualified is True
        assert out[1].qualified is False

    def test_provider_exception_isolated(self):
        def provider(sym):
            if sym == "BOOM":
                raise RuntimeError("down")
            return _last_bar_cross_up_frame()

        out = qualified_entries(["BOOM", "OK"], provider, _LOOSE_SCREEN, _UNGATED_AVT)
        assert [d.symbol for d in out] == ["OK"]


# ─── Combined backtest ───────────────────────────────────────────────────────


def _momentum_frame(n: int = 320, block: int = 30) -> pd.DataFrame:
    prices = [100.0]
    for t in range(1, n):
        up = (t // block) % 2 == 0
        prices.append(prices[-1] * (1.01 if up else 0.99))
    close = pd.Series(prices)
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close * 1.004,
            "low": close * 0.996,
            "close": close,
            "volume": pd.Series([1000.0] * n),
        }
    )


_CHG_ONLY = ScreenerFilters(
    x_from_50_min=None, x_from_50_max=None, rvol_min=None, x_from_lod_max=None, chg_pct_min=0.0
)


class TestCombinedBacktest:
    def test_buckets_partition_screener_passes(self):
        res = run_combined_backtest(
            {"MOM": _momentum_frame()},
            _CHG_ONLY,
            _UNGATED_AVT,
            horizon=5,
            step=3,
            min_history=60,
        )
        assert isinstance(res, CombinedBacktestResult)
        assert res.n_screener_pass == res.combined.n + res.screener_only.n
        assert res.n_screener_pass > 0

    def test_impossible_score_floor_sends_all_to_screener_only(self):
        res = run_combined_backtest(
            {"MOM": _momentum_frame()},
            _CHG_ONLY,
            _UNGATED_AVT,
            min_avt_score=1000.0,
            horizon=5,
            step=3,
            min_history=60,
        )
        assert res.combined.n == 0
        assert res.screener_only.n == res.n_screener_pass
        assert np.isnan(res.edge)  # no combined bucket to compare

    def test_short_frame_yields_no_decisions(self):
        res = run_combined_backtest(
            {"SHORT": _momentum_frame(n=50)}, _CHG_ONLY, _UNGATED_AVT, min_history=210
        )
        assert res.n_screener_pass == 0
        assert res.symbols == []

    def test_invalid_horizon_raises(self):
        with pytest.raises(ValueError):
            run_combined_backtest({"MOM": _momentum_frame()}, horizon=0)

    def test_edge_is_finite_when_both_buckets_populated(self):
        res = run_combined_backtest(
            {"MOM": _momentum_frame()},
            _CHG_ONLY,
            _UNGATED_AVT,
            horizon=5,
            step=2,
            min_history=60,
        )
        if res.combined.n > 0 and res.screener_only.n > 0:
            assert np.isfinite(res.edge)
            assert np.isfinite(res.combined.mean_fwd_return)
