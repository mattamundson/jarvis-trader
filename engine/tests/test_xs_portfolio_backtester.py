"""R3/T13: dollar-neutral cross-sectional portfolio backtester."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("API_KEY", "test-key")
_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from backtest.xs_portfolio_backtester import (  # noqa: E402
    run_xs_portfolio_backtest,
    temporal_split_verdict,
)


def _panel(data: dict, n: int) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(data, index=idx)


def test_long_winner_short_loser_is_profitable():
    # A compounds +10%/bar, B compounds -10%/bar -> long A / short B pays.
    a = [100.0 * (1.1**k) for k in range(6)]
    b = [100.0 * (0.9**k) for k in range(6)]
    res = run_xs_portfolio_backtest(
        _panel({"A": a, "B": b}, 6), lookback=1, top_k=1, hold_bars=1, cost_bps=0.0
    )
    assert res["total_trades"] >= 3
    assert res["total_return_pct"] > 0
    # Each period: +0.5*0.10 - 0.5*(-0.10) = +0.10 gross.
    assert res["trades"][0]["ret"] == pytest.approx(0.10)


def test_common_market_move_nets_to_zero():
    # All symbols move identically -> dollar-neutral book cancels regardless of
    # the (arbitrary) tie-break in ranking.
    series = [100.0 * (1.1**k) for k in range(5)]
    res = run_xs_portfolio_backtest(
        _panel({"A": list(series), "B": list(series)}, 5),
        lookback=1,
        top_k=1,
        hold_bars=1,
        cost_bps=0.0,
    )
    for t in res["trades"]:
        assert abs(t["ret"]) < 1e-9


def test_cost_reduces_return():
    a = [100.0 * (1.1**k) for k in range(6)]
    b = [100.0 * (0.9**k) for k in range(6)]
    panel = _panel({"A": a, "B": b}, 6)
    free = run_xs_portfolio_backtest(panel, lookback=1, top_k=1, hold_bars=1, cost_bps=0.0)
    costly = run_xs_portfolio_backtest(panel, lookback=1, top_k=1, hold_bars=1, cost_bps=50.0)
    assert costly["total_return_pct"] < free["total_return_pct"]


def test_metric_surface_has_gate_keys():
    a = [100.0 * (1.1**k) for k in range(6)]
    b = [100.0 * (0.9**k) for k in range(6)]
    res = run_xs_portfolio_backtest(_panel({"A": a, "B": b}, 6), lookback=1)
    for key in (
        "profit_factor",
        "max_drawdown_pct",
        "sharpe_ratio",
        "total_trades",
        "trades",
        "equity_curve",
        "win_rate",
    ):
        assert key in res


def test_too_short_panel_returns_safe_empty():
    res = run_xs_portfolio_backtest(_panel({"A": [1.0, 2.0], "B": [1.0, 2.0]}, 2), lookback=5)
    assert res["total_trades"] == 0
    assert res["profit_factor"] == 0.0
    assert res["equity_curve"] == [100_000.0]


def test_profit_factor_and_winrate_on_known_case():
    # Winner/loser pair -> every period wins -> PF inf, win_rate 1.0.
    a = [100.0 * (1.1**k) for k in range(6)]
    b = [100.0 * (0.9**k) for k in range(6)]
    res = run_xs_portfolio_backtest(
        _panel({"A": a, "B": b}, 6), lookback=1, top_k=1, hold_bars=1, cost_bps=0.0
    )
    assert res["win_rate"] == 1.0
    assert res["profit_factor"] == float("inf")


def test_temporal_split_strong_when_both_halves_profitable():
    # Both halves trend (winner up, loser down) -> momentum pays in each era.
    a = [100.0 * (1.1**k) for k in range(12)]
    b = [100.0 * (0.9**k) for k in range(12)]
    v = temporal_split_verdict(
        _panel({"A": a, "B": b}, 12), lookback=1, top_k=1, hold_bars=1, cost_bps=0.0, n_segments=2
    )
    assert v["verdict"] == "STRONG"
    assert v["all_profitable"] is True
    assert all(s["total_return_pct"] > 0 for s in v["segments"])


def test_temporal_split_catches_nonstationary_backloaded_edge():
    # H1: zigzag (1-bar momentum gets whipsawed -> loses). H2: clean trend -> wins.
    # A pooled view could look fine; the chronological split MUST fail it.
    a_h1, b_h1 = [100.0, 110.0, 100.0, 110.0, 100.0, 110.0], [100.0, 90.0, 100.0, 90.0, 100.0, 90.0]
    a_h2 = [110.0 * (1.1**k) for k in range(6)]
    b_h2 = [90.0 * (0.9**k) for k in range(6)]
    panel = _panel({"A": a_h1 + a_h2, "B": b_h1 + b_h2}, 12)
    v = temporal_split_verdict(panel, lookback=1, top_k=1, hold_bars=1, cost_bps=0.0, n_segments=2)
    assert v["verdict"] == "FAIL"  # not stationary
    assert v["segments"][0]["total_return_pct"] < 0  # H1 loses
    assert v["segments"][1]["total_return_pct"] > 0  # H2 wins (the back-loaded era)


def test_dispersion_filter_flattens_low_dispersion_periods():
    # Two regimes: identical moves (low dispersion) then a divergence (high).
    a = [100.0, 110.0, 121.0, 133.0, 180.0, 250.0]
    b = [100.0, 110.0, 121.0, 133.0, 90.0, 60.0]
    panel = _panel({"A": a, "B": b}, 6)
    # A high threshold flattens the early identical-move periods -> fewer/zero-ret trades.
    filtered = run_xs_portfolio_backtest(
        panel, lookback=1, top_k=1, hold_bars=1, cost_bps=0.0, dispersion_min=0.05
    )
    unfiltered = run_xs_portfolio_backtest(
        panel, lookback=1, top_k=1, hold_bars=1, cost_bps=0.0, dispersion_min=None
    )
    # Filter zeroes the low-dispersion book -> at least one period has ret 0 under filter.
    assert any(t["ret"] == 0.0 for t in filtered["trades"])
    # Both run the same number of periods (filter flattens, doesn't drop the bar).
    assert filtered["total_trades"] == unfiltered["total_trades"]
