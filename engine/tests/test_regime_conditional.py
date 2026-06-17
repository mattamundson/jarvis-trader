"""Tests for regime-conditional performance reporting.

Tests cover:
  1. tag_regime_vol: regime tagging and RV computation
  2. assign_vol_terciles: tercile cut-points including degenerate cases
  3. bucket_trades: PF/win-rate per bucket; inf-PF; empty bucket handling
  4. Gate-invariance: regime-conditional code cannot change gate verdict
  5. regime_report.run(): strategies with and without breakdown field

Run (from engine/):
    ../.venv/Scripts/python -m pytest tests/test_regime_conditional.py -p no:cacheprovider --no-header -q
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
import pytest

from backtest.regime_conditional import (
    assign_vol_terciles,
    bucket_trades,
    tag_regime_vol,
)

# ---------------------------------------------------------------------------
# Helpers — synthetic data builders
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int, *, trend: bool = False, base_price: float = 100.0,
                seed: int = 42) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame.

    If trend=True, prices march steadily upward (strong-trend scenario).
    If trend=False, prices oscillate around the base (range scenario).
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-02 09:30", periods=n, freq="5min", tz="UTC")
    if trend:
        # Consistent uptrend: each close higher than the previous
        close = base_price + np.arange(n) * 0.5 + rng.normal(0, 0.05, n)
    else:
        # Flat oscillation: random walk around base_price with tiny steps
        close = base_price + rng.normal(0, 0.05, n).cumsum()
        close = close - close.mean() + base_price  # re-centre
    high = close + abs(rng.normal(0, 0.03, n))
    low = close - abs(rng.normal(0, 0.03, n))
    open_ = close - rng.normal(0, 0.02, n)
    volume = rng.integers(100, 500, n).astype(float)
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )
    return df


@dataclass
class _FakeTrade:
    """Minimal Trade stand-in for bucket_trades tests."""
    entry_date: datetime
    pnl: float
    symbol: str = "MES"
    direction: str = "long"
    entry_price: float = 100.0
    exit_price: float = 101.0
    stop_price: float = 99.0
    target_1: float = 102.0
    target_2: float = 103.0
    contracts: int = 1
    multiplier: float = 5.0
    exit_date: Optional[datetime] = None
    exit_reason: str = "target_1"
    holding_bars: int = 5
    regime: str = ""
    bias: str = ""


@dataclass
class _FakeOOSResult:
    """Minimal BacktestResult stand-in."""
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float
    total_trades: int
    trades: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# 1. tag_regime_vol
# ---------------------------------------------------------------------------

class TestTagRegimeVol:
    def test_strong_uptrend_classifies_mostly_trending(self):
        """A steady uptrend should produce ADX >= 25 (TRENDING) for the majority
        of bars once the ADX indicator has enough warm-up bars (28+)."""
        n = 200
        df = _make_ohlcv(n, trend=True, seed=1)
        out = tag_regime_vol(df)
        assert "rc_regime" in out.columns
        assert "rc_rv_ann_pct" in out.columns
        # After ADX warm-up (~28 bars) the trend should be well-established.
        warm = out.iloc[50:]
        trending_frac = (warm["rc_regime"] == "TRENDING").mean()
        assert trending_frac > 0.5, (
            f"Expected >50% TRENDING bars in a strong uptrend; got {trending_frac:.1%}"
        )

    def test_flat_noisy_classifies_mostly_range(self):
        """A flat, noisy oscillation should produce ADX < 25 (RANGE) for most bars."""
        n = 200
        df = _make_ohlcv(n, trend=False, seed=7)
        out = tag_regime_vol(df)
        warm = out.iloc[50:]
        range_frac = (warm["rc_regime"] == "RANGE").mean()
        assert range_frac > 0.5, (
            f"Expected >50% RANGE bars in flat oscillation; got {range_frac:.1%}"
        )

    def test_rv_ann_pct_is_finite_and_positive(self):
        """rc_rv_ann_pct must be finite and positive where it is not NaN."""
        df = _make_ohlcv(100, trend=False, seed=99)
        out = tag_regime_vol(df)
        valid = out["rc_rv_ann_pct"].dropna()
        assert len(valid) > 0
        assert (valid > 0).all(), "All non-NaN RV values must be positive"
        assert valid.apply(lambda v: math.isfinite(v)).all(), "All non-NaN RV values must be finite"

    def test_does_not_mutate_input(self):
        """tag_regime_vol must not modify the caller's DataFrame."""
        df = _make_ohlcv(50, trend=True)
        cols_before = set(df.columns)
        _ = tag_regime_vol(df)
        assert set(df.columns) == cols_before

    def test_regime_labels_are_valid(self):
        """Every rc_regime value must be either TRENDING or RANGE."""
        df = _make_ohlcv(60, trend=False, seed=5)
        out = tag_regime_vol(df)
        invalid = out["rc_regime"][~out["rc_regime"].isin({"TRENDING", "RANGE"})]
        assert len(invalid) == 0, f"Invalid regime labels: {invalid.unique()}"

    def test_bar_minutes_affects_rv_magnitude(self):
        """Shorter bars (1-min) should produce higher annualized RV than 5-min
        since bars_per_year is larger and the rolling window spans less calendar time."""
        df = _make_ohlcv(100, trend=False, seed=3)
        out_5m = tag_regime_vol(df, bar_minutes=5)
        out_1m = tag_regime_vol(df, bar_minutes=1)
        # bar_minutes=1 => sqrt(bars_per_year) is ~sqrt(5) times larger
        median_5m = out_5m["rc_rv_ann_pct"].dropna().median()
        median_1m = out_1m["rc_rv_ann_pct"].dropna().median()
        assert median_1m > median_5m


# ---------------------------------------------------------------------------
# 2. assign_vol_terciles
# ---------------------------------------------------------------------------

class TestAssignVolTerciles:
    def test_known_distribution(self):
        """p33 and p67 should closely match numpy's percentile for a large series."""
        rng = np.random.default_rng(42)
        values = pd.Series(rng.uniform(0, 100, 1000))
        p33, p67 = assign_vol_terciles(values)
        expected_p33 = np.percentile(values, 33.0)
        expected_p67 = np.percentile(values, 67.0)
        assert abs(p33 - expected_p33) < 1e-8
        assert abs(p67 - expected_p67) < 1e-8

    def test_p33_le_p67(self):
        """Cut points must be ordered: p33 <= p67."""
        values = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0])
        p33, p67 = assign_vol_terciles(values)
        assert p33 <= p67

    def test_constant_series_degenerate(self):
        """A constant series should return the same value for both cut-points."""
        values = pd.Series([5.0] * 100)
        p33, p67 = assign_vol_terciles(values)
        assert p33 == p67 == 5.0

    def test_empty_series(self):
        """An empty series should return (0.0, 0.0) without raising."""
        p33, p67 = assign_vol_terciles(pd.Series([], dtype=float))
        assert p33 == 0.0 and p67 == 0.0

    def test_nan_values_ignored(self):
        """NaN values should be dropped before computing percentiles."""
        values = pd.Series([float("nan")] * 5 + list(range(1, 11)))
        p33_nan, p67_nan = assign_vol_terciles(values)
        clean = pd.Series(list(range(1, 11)))
        p33_clean, p67_clean = assign_vol_terciles(clean)
        assert abs(p33_nan - p33_clean) < 1e-8
        assert abs(p67_nan - p67_clean) < 1e-8

    def test_two_element_series(self):
        """Fewer-than-3-element series: returns (min, max)."""
        values = pd.Series([3.0, 7.0])
        p33, p67 = assign_vol_terciles(values)
        assert p33 == 3.0 and p67 == 7.0


# ---------------------------------------------------------------------------
# 3. bucket_trades
# ---------------------------------------------------------------------------

def _ts(offset_minutes: int = 0) -> datetime:
    """Helper: UTC datetime with minute offset."""
    return datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc) + pd.Timedelta(minutes=offset_minutes)


class TestBucketTrades:
    def _make_trades_and_maps(self):
        """Four trades across two regimes (TRENDING/RANGE) and two vol buckets (LOW/HIGH)."""
        t1 = _FakeTrade(entry_date=_ts(0), pnl=100.0)   # TRENDING, LOW vol  — winner
        t2 = _FakeTrade(entry_date=_ts(5), pnl=-50.0)   # TRENDING, HIGH vol — loser
        t3 = _FakeTrade(entry_date=_ts(10), pnl=80.0)   # RANGE, LOW vol     — winner
        t4 = _FakeTrade(entry_date=_ts(15), pnl=-30.0)  # RANGE, HIGH vol    — loser

        regime_by_entry = {
            _ts(0): "TRENDING",
            _ts(5): "TRENDING",
            _ts(10): "RANGE",
            _ts(15): "RANGE",
        }
        # p33=5.0 (cut LOW/MID), p67=15.0 (cut MID/HIGH)
        rv_by_entry = {
            _ts(0): 3.0,    # LOW
            _ts(5): 20.0,   # HIGH
            _ts(10): 3.0,   # LOW
            _ts(15): 20.0,  # HIGH
        }
        vol_edges = (5.0, 15.0)
        return [t1, t2, t3, t4], regime_by_entry, rv_by_entry, vol_edges

    def test_pf_per_bucket(self):
        trades, regime_by_entry, rv_by_entry, vol_edges = self._make_trades_and_maps()
        result = bucket_trades(trades, regime_by_entry, rv_by_entry, vol_edges)

        # TRENDING_LOW: one winner (+100), no loser -> PF = inf
        trending_low = result["by_regime_vol"].get("TRENDING_LOW")
        assert trending_low is not None, "TRENDING_LOW cell must exist"
        assert trending_low["profit_factor"] == float("inf"), "PF should be inf (no losers)"
        assert trending_low["trades"] == 1
        assert trending_low["win_rate"] == 1.0

        # TRENDING_HIGH: one loser (-50), no winner -> PF = 0.0
        trending_high = result["by_regime_vol"].get("TRENDING_HIGH")
        assert trending_high is not None, "TRENDING_HIGH cell must exist"
        assert trending_high["profit_factor"] == 0.0
        assert trending_high["win_rate"] == 0.0

        # RANGE_LOW: one winner (+80) -> PF = inf
        range_low = result["by_regime_vol"].get("RANGE_LOW")
        assert range_low is not None
        assert range_low["profit_factor"] == float("inf")

    def test_win_rate_known(self):
        trades, regime_by_entry, rv_by_entry, vol_edges = self._make_trades_and_maps()
        result = bucket_trades(trades, regime_by_entry, rv_by_entry, vol_edges)

        # by_regime TRENDING: t1 (+100), t2 (-50) -> win_rate 0.5, pf = 100/50 = 2.0
        trending = result["by_regime"].get("TRENDING")
        assert trending is not None
        assert trending["win_rate"] == 0.5
        assert abs(trending["profit_factor"] - 2.0) < 1e-6

        # by_regime RANGE: t3 (+80), t4 (-30) -> pf = 80/30 ~ 2.667
        range_ = result["by_regime"].get("RANGE")
        assert range_ is not None
        assert abs(range_["profit_factor"] - 80 / 30) < 1e-4

    def test_pf_inf_when_no_losers(self):
        """PF is inf when ALL trades in a bucket are winners."""
        t = _FakeTrade(entry_date=_ts(0), pnl=200.0)
        result = bucket_trades(
            [t],
            {_ts(0): "TRENDING"},
            {_ts(0): 3.0},
            (5.0, 15.0),
        )
        pf = result["by_regime"]["TRENDING"]["profit_factor"]
        assert pf == float("inf")

    def test_empty_bucket_omitted(self):
        """Cells with zero trades are not present in the output (not crashing)."""
        t = _FakeTrade(entry_date=_ts(0), pnl=50.0)
        result = bucket_trades(
            [t],
            {_ts(0): "TRENDING"},
            {_ts(0): 3.0},
            (5.0, 15.0),
        )
        # RANGE cells should be absent, not zero-valued or raising.
        assert "RANGE" not in result["by_regime"]
        assert all("RANGE" not in k for k in result["by_regime_vol"])

    def test_empty_trades_list(self):
        """Empty trades list produces empty buckets, no exception."""
        result = bucket_trades([], {}, {}, (5.0, 15.0))
        assert result["by_regime_vol"] == {}
        assert result["by_regime"] == {}
        assert result["by_vol"] == {}

    def test_marginal_by_vol(self):
        trades, regime_by_entry, rv_by_entry, vol_edges = self._make_trades_and_maps()
        result = bucket_trades(trades, regime_by_entry, rv_by_entry, vol_edges)
        # LOW bucket: t1 (+100) + t3 (+80) -> 2 trades, both winners
        low = result["by_vol"].get("LOW")
        assert low is not None
        assert low["trades"] == 2
        assert low["win_rate"] == 1.0
        assert low["profit_factor"] == float("inf")


# ---------------------------------------------------------------------------
# 4. Gate-invariance test (THE SAFETY GUARD)
# ---------------------------------------------------------------------------

class TestGateInvariance:
    """Prove regime-conditional code cannot change gate verdict, pf_ci_lower, p_edge, dsr."""

    def _fake_oos_results(self):
        """Six OOS windows: 5 profitable (PF>1) and 1 unprofitable."""
        return [
            _FakeOOSResult(profit_factor=1.8, max_drawdown_pct=0.02, sharpe_ratio=1.5, total_trades=30),
            _FakeOOSResult(profit_factor=1.5, max_drawdown_pct=0.03, sharpe_ratio=1.2, total_trades=25),
            _FakeOOSResult(profit_factor=1.3, max_drawdown_pct=0.025, sharpe_ratio=0.9, total_trades=20),
            _FakeOOSResult(profit_factor=2.1, max_drawdown_pct=0.015, sharpe_ratio=2.0, total_trades=35),
            _FakeOOSResult(profit_factor=1.6, max_drawdown_pct=0.02, sharpe_ratio=1.4, total_trades=28),
            _FakeOOSResult(profit_factor=0.8, max_drawdown_pct=0.04, sharpe_ratio=-0.3, total_trades=10),
        ]

    def test_gate_verdict_unchanged_by_regime_code(self):
        """_compute_gate_v2 output is byte-identical regardless of regime_conditional."""
        from backtest.study_wfo_runner import _compute_gate_v2

        oos = self._fake_oos_results()
        fixed = {
            "fixed_params_min_pf": 1.2,
            "fixed_params_mean_pf": 1.5,
            "fixed_params_max_pf": 2.0,
            "n_combos_with_trades": 4,
            "combo_results": [],
        }
        cost = {
            "cost_survives_through": "realistic",
            "tier_results": {
                "optimistic": {"pf": 1.8, "trades": 25, "passes": True},
                "realistic": {"pf": 1.5, "trades": 25, "passes": True},
                "pessimistic": {"pf": 0.9, "trades": 20, "passes": False},
            },
        }
        n_grid = 4

        # Compute gate WITHOUT touching regime_conditional
        gate_baseline = _compute_gate_v2(oos, n_grid, fixed, cost)

        # Now simulate calling regime_conditional code
        from backtest.regime_conditional import (
            assign_vol_terciles,
            bucket_trades,
        )
        # Regime code runs on separate data — it cannot feed back into gate
        rv_series = pd.Series([10.0, 20.0, 30.0, 5.0, 15.0, 25.0])
        p33, p67 = assign_vol_terciles(rv_series)
        dummy_trades = [_FakeTrade(entry_date=_ts(i * 5), pnl=float(i * 10 - 5)) for i in range(6)]
        regime_map = {_ts(i * 5): ("TRENDING" if i % 2 == 0 else "RANGE") for i in range(6)}
        rv_map = {_ts(i * 5): float(rv_series.iloc[i]) for i in range(6)}
        _ = bucket_trades(dummy_trades, regime_map, rv_map, (p33, p67))

        # Gate output must be identical — regime code is a pure side branch
        gate_after = _compute_gate_v2(oos, n_grid, fixed, cost)

        assert gate_after["verdict"] == gate_baseline["verdict"], "verdict changed!"
        assert gate_after["passed_via"] == gate_baseline["passed_via"], "passed_via changed!"
        assert gate_after["pf_ci_lower"] == gate_baseline["pf_ci_lower"], "pf_ci_lower changed!"
        assert gate_after["p_edge"] == gate_baseline["p_edge"], "p_edge changed!"
        assert gate_after["dsr"] == gate_baseline["dsr"], "dsr changed!"
        assert gate_after["mc_95th_dd"] == gate_baseline["mc_95th_dd"], "mc_95th_dd changed!"

    def test_compute_regime_conditional_error_never_raises(self):
        """_compute_regime_conditional must never propagate exceptions."""
        from backtest.study_wfo_runner import _compute_regime_conditional

        # Pass intentionally broken window data — must return {"error": ...} not raise.
        broken = [(object(), None)]  # (not a BacktestResult, not a DataFrame)
        result = _compute_regime_conditional(broken)
        # Either an error dict or a valid result — never an exception.
        assert isinstance(result, dict)

    def test_compute_regime_conditional_empty_data(self):
        """Empty window list returns a valid (empty) dict, no error key."""
        from backtest.study_wfo_runner import _compute_regime_conditional

        result = _compute_regime_conditional([])
        assert isinstance(result, dict)
        assert "error" not in result
        assert result.get("total_trades_classified") == 0


# ---------------------------------------------------------------------------
# 5. regime_report.run() with fixture verdicts
# ---------------------------------------------------------------------------

class TestRegimeReport:
    def _make_verdict_with_breakdown(self, sid: str, gate: str = "PASS") -> dict:
        return {
            "_id": sid,
            "symbol": "MGC",
            "family": "trend_go",
            "verdict": gate,
            "gate_v2_metrics": {"pf_ci_lower": 1.25, "p_edge": 0.96, "dsr": 0.45},
            "wfo_config": {"n_oos_windows": 8},
            "regime_conditional": {
                "classifier": "adx>=25 trending; rv tercile per-window",
                "vol_edges": {"p33": 5.0, "p67": 15.0},
                "by_regime": {
                    "TRENDING": {"trades": 40, "win_rate": 0.68, "profit_factor": 2.5,
                                 "total_pnl": 800.0, "avg_pnl": 20.0},
                    "RANGE": {"trades": 20, "win_rate": 0.40, "profit_factor": 0.7,
                              "total_pnl": -150.0, "avg_pnl": -7.5},
                },
                "by_regime_vol": {},
                "by_vol": {},
                "total_trades_classified": 60,
                "note": "DIAGNOSTIC ONLY - does not affect gate verdict",
            },
        }

    def _make_verdict_no_breakdown(self, sid: str, gate: str = "FAIL") -> dict:
        return {
            "_id": sid,
            "symbol": "MES",
            "family": "trend_go",
            "verdict": gate,
            "gate_v2_metrics": {"pf_ci_lower": 0.9, "p_edge": 0.60, "dsr": 0.05},
            "wfo_config": {"n_oos_windows": 6},
            # No "regime_conditional" field — pre-existing verdict
        }

    def test_run_with_mixed_verdicts(self, monkeypatch):
        """run() handles one verdict with breakdown + one without; no crash."""
        from backtest import regime_report as rr

        fixture = [
            self._make_verdict_with_breakdown("MGC_trend_go_rank1"),
            self._make_verdict_no_breakdown("MES_trend_go_rank1"),
        ]
        monkeypatch.setattr(rr, "load_verdicts", lambda *a, **k: fixture)

        report = rr.run()

        assert report["n_verdicts_total"] == 2
        assert report["n_with_breakdown"] == 1
        assert report["n_no_breakdown"] == 1

    def test_no_breakdown_verdict_reported_not_crashing(self, monkeypatch):
        """Verdict without regime_conditional is placed in no_breakdown, not strategies."""
        from backtest import regime_report as rr

        fixture = [self._make_verdict_no_breakdown("MES_trend_go_rank1")]
        monkeypatch.setattr(rr, "load_verdicts", lambda *a, **k: fixture)

        report = rr.run()
        ids_in_strategies = [s["id"] for s in report["strategies"]]
        ids_in_no_breakdown = [e["id"] for e in report["no_breakdown"]]

        assert "MES_trend_go_rank1" not in ids_in_strategies
        assert "MES_trend_go_rank1" in ids_in_no_breakdown

    def test_trending_edge_hypothesis_detected(self, monkeypatch):
        """Strategy with TRENDING PF >> blended PF triggers trending_edge_hypothesis=True."""
        from backtest import regime_report as rr

        # blended pf_ci_lower = 1.25; TRENDING PF = 2.5 -> delta = 1.25 > threshold 0.20
        fixture = [self._make_verdict_with_breakdown("MGC_trend_go_rank1")]
        monkeypatch.setattr(rr, "load_verdicts", lambda *a, **k: fixture)

        report = rr.run()
        assert report["n_trending_edge_hypothesis"] == 1
        assert report["trending_edge_ids"] == ["MGC_trend_go_rank1"]

    def test_error_field_treated_as_no_breakdown(self, monkeypatch):
        """A verdict with regime_conditional={"error": ...} is treated as no breakdown."""
        from backtest import regime_report as rr

        fixture = [{
            "_id": "MES_broken_rank1",
            "symbol": "MES",
            "family": "trend_go",
            "verdict": "FAIL",
            "gate_v2_metrics": {"pf_ci_lower": 0.8},
            "regime_conditional": {"error": "something went wrong"},
        }]
        monkeypatch.setattr(rr, "load_verdicts", lambda *a, **k: fixture)

        report = rr.run()
        assert report["n_no_breakdown"] == 1
        assert report["n_with_breakdown"] == 0

    def test_empty_verdict_dir(self, monkeypatch):
        """Empty verdict dir produces zero counts, no exception."""
        from backtest import regime_report as rr

        monkeypatch.setattr(rr, "load_verdicts", lambda *a, **k: [])

        report = rr.run()
        assert report["n_verdicts_total"] == 0
        assert report["n_with_breakdown"] == 0
        assert report["n_no_breakdown"] == 0
