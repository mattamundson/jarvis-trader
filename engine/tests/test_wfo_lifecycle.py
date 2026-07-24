"""Tests for engine/backtest/wfo_lifecycle.py.

Covers all public functions: generate_windows (bar-count + date-offset),
grid_search_is, run_oos_window, run_fixed_params_sweep, run_cost_sweep,
compute_gate_v2, and run_wfo end-to-end on synthetic data.

Uses SimpleNamespace duck-type stubs for unit tests of helper functions,
and the real Backtester + SMA trend signals for the E2E test.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from backtest.wfo_lifecycle import (
    OOSResult,
    WFOConfig,
    compute_gate_v2,
    generate_windows,
    grid_search_is,
    run_cost_sweep,
    run_fixed_params_sweep,
    run_oos_window,
    run_wfo,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_ohlcv(n: int = 300, seed: int = 42) -> pd.DataFrame:
    """Deterministic synthetic OHLCV DataFrame with a DatetimeIndex."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(loc=0.0003, scale=0.003, size=n)
    close = 2000.0 * np.cumprod(1 + returns)
    noise = rng.uniform(0.001, 0.003, size=n)
    high = close * (1 + noise)
    low = close * (1 - noise)
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    idx = pd.date_range(
        start=datetime(2024, 1, 2, 9, 0, tzinfo=timezone.utc),
        periods=n,
        freq="1h",
        tz="UTC",
    )
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 100},
        index=idx,
    )


def _fake_result(
    profit_factor: float = 1.5,
    max_drawdown_pct: float = -0.02,
    sharpe_ratio: float = 1.0,
    total_trades: int = 10,
) -> object:
    """Minimal duck-typed object standing in for BacktestResult in unit tests."""
    from types import SimpleNamespace

    return SimpleNamespace(
        profit_factor=profit_factor,
        max_drawdown_pct=max_drawdown_pct,
        sharpe_ratio=sharpe_ratio,
        total_trades=total_trades,
    )


def _making_run_fn(results: list[object]):
    """run_fn factory that yields successive results from a list."""
    results_iter = iter(results)

    def _run_fn(df: pd.DataFrame, params: dict) -> object:
        return next(results_iter)

    return _run_fn


# ---------------------------------------------------------------------------
# generate_windows — bar-count mode
# ---------------------------------------------------------------------------


def test_generate_windows_bar_count_window_count():
    df = _make_ohlcv(300)
    cfg = WFOConfig(train_len=100, test_len=50, step_len=50)
    windows = generate_windows(df, cfg)
    # cursor=0: [0:100 train, 100:150 test] ✓
    # cursor=50: [50:150 train, 150:200 test] ✓
    # cursor=100: [100:200 train, 200:250 test] ✓
    # cursor=150: [150:250 train, 250:300 test] ✓
    # cursor=200: 200+100+50=350 > 300 → stop
    assert len(windows) == 4


def test_generate_windows_bar_count_slices_non_overlapping():
    df = _make_ohlcv(300)
    cfg = WFOConfig(train_len=100, test_len=50, step_len=100)
    windows = generate_windows(df, cfg)
    for win in windows:
        assert win["n_train"] == 100
        assert win["n_test"] == 50
        # train and test must not share any index values
        assert len(set(win["df_train"].index) & set(win["df_test"].index)) == 0


def test_generate_windows_bar_count_required_keys():
    df = _make_ohlcv(200)
    cfg = WFOConfig(train_len=100, test_len=50, step_len=50)
    windows = generate_windows(df, cfg)
    assert len(windows) >= 1
    required = {
        "window_num",
        "train_start",
        "train_end",
        "test_start",
        "test_end",
        "n_train",
        "n_test",
        "df_train",
        "df_test",
    }
    for win in windows:
        assert required.issubset(win.keys())


def test_generate_windows_bar_count_min_bars_skips_short():
    df = _make_ohlcv(100)
    # train=80, test=10 → n_test=10 < min_bars=30 → all skipped
    cfg = WFOConfig(train_len=80, test_len=10, step_len=10, min_bars=30)
    windows = generate_windows(df, cfg)
    assert windows == []


def test_generate_windows_df_too_short_returns_empty():
    df = _make_ohlcv(50)
    cfg = WFOConfig(train_len=100, test_len=50, step_len=50)
    windows = generate_windows(df, cfg)
    assert windows == []


# ---------------------------------------------------------------------------
# generate_windows — date-offset mode
# ---------------------------------------------------------------------------


def test_generate_windows_date_offset_produces_windows():
    # 400 hourly bars ≈ 16 calendar days
    df = _make_ohlcv(400)
    cfg = WFOConfig(
        train_len=pd.DateOffset(days=5),
        test_len=pd.DateOffset(days=2),
        step_len=pd.DateOffset(days=2),
        min_bars=1,
    )
    windows = generate_windows(df, cfg)
    assert len(windows) >= 1
    for win in windows:
        assert len(win["df_train"]) >= 1
        assert len(win["df_test"]) >= 1


def test_generate_windows_date_offset_window_nums_sequential():
    df = _make_ohlcv(400)
    cfg = WFOConfig(
        train_len=pd.DateOffset(days=5),
        test_len=pd.DateOffset(days=2),
        step_len=pd.DateOffset(days=2),
        min_bars=1,
    )
    windows = generate_windows(df, cfg)
    nums = [w["window_num"] for w in windows]
    assert nums == list(range(1, len(windows) + 1))


# ---------------------------------------------------------------------------
# grid_search_is
# ---------------------------------------------------------------------------


def test_grid_search_is_picks_best_pf():
    results = [_fake_result(profit_factor=0.8), _fake_result(profit_factor=1.9)]
    grid = [{"fast": 10}, {"fast": 20}]
    run_fn = _making_run_fn(results)
    best_params, best_result = grid_search_is(_make_ohlcv(50), grid, run_fn)
    assert best_params == {"fast": 20}
    assert best_result.profit_factor == 1.9  # type: ignore[union-attr]


def test_grid_search_is_all_raise_returns_none():
    def _raising(df, params):
        raise RuntimeError("boom")

    grid = [{"fast": 10}, {"fast": 20}]
    best_params, best_result = grid_search_is(_make_ohlcv(50), grid, _raising)
    assert best_params is None
    assert best_result is None


def test_grid_search_is_min_trades_filter():
    # First combo has 0 trades (below min), second has 5 → second wins
    results = [
        _fake_result(profit_factor=99.0, total_trades=0),
        _fake_result(profit_factor=1.2, total_trades=5),
    ]
    grid = [{"fast": 10}, {"fast": 20}]
    run_fn = _making_run_fn(results)
    best_params, _ = grid_search_is(_make_ohlcv(50), grid, run_fn, min_trades=1)
    assert best_params == {"fast": 20}


# ---------------------------------------------------------------------------
# run_oos_window
# ---------------------------------------------------------------------------


def test_run_oos_window_returns_oos_result():
    result = _fake_result(
        profit_factor=1.4, max_drawdown_pct=-0.03, sharpe_ratio=0.9, total_trades=12
    )
    oos = run_oos_window(
        _make_ohlcv(50),
        params={"fast": 20},
        run_fn=lambda df, p: result,
        window_idx=3,
        is_pf=1.8,
        is_trades=20,
    )
    assert oos is not None
    assert oos.window_idx == 3
    assert oos.profit_factor == pytest.approx(1.4)
    assert oos.max_drawdown_pct == pytest.approx(-0.03)
    assert oos.total_trades == 12
    assert oos.is_pf == pytest.approx(1.8)
    assert oos.best_params == {"fast": 20}


def test_run_oos_window_exception_returns_none():
    def _raise(df, params):
        raise ValueError("data error")

    oos = run_oos_window(_make_ohlcv(50), {}, _raise, window_idx=1)
    assert oos is None


# ---------------------------------------------------------------------------
# run_fixed_params_sweep
# ---------------------------------------------------------------------------


def test_run_fixed_params_sweep_structure():
    results = [_fake_result(1.2, total_trades=5), _fake_result(1.8, total_trades=8)]
    grid = [{"fast": 10}, {"fast": 20}]
    run_fn = _making_run_fn(results)
    out = run_fixed_params_sweep(_make_ohlcv(50), grid, run_fn)
    assert "fixed_params_min_pf" in out
    assert "fixed_params_mean_pf" in out
    assert "fixed_params_max_pf" in out
    assert "n_combos_with_trades" in out
    assert "combo_results" in out
    assert out["fixed_params_min_pf"] == pytest.approx(1.2, abs=1e-3)
    assert out["fixed_params_max_pf"] == pytest.approx(1.8, abs=1e-3)
    assert out["n_combos_with_trades"] == 2


def test_run_fixed_params_sweep_all_fail():
    def _raise(df, params):
        raise RuntimeError

    out = run_fixed_params_sweep(_make_ohlcv(50), [{"fast": 10}], _raise)
    assert out["fixed_params_min_pf"] == 0.0
    assert out["n_combos_with_trades"] == 0


# ---------------------------------------------------------------------------
# run_cost_sweep
# ---------------------------------------------------------------------------

_COST_TIERS = {
    "optimistic": {"commission": 0.31, "slippage_ticks": 1.0},
    "realistic": {"commission": 0.62, "slippage_ticks": 2.0},
    "pessimistic": {"commission": 1.24, "slippage_ticks": 3.0},
    "catastrophic": {"commission": 2.48, "slippage_ticks": 4.0},
}


def test_run_cost_sweep_structure():
    run_fn = lambda df, p: _fake_result(1.5, total_trades=5)  # noqa: E731
    out = run_cost_sweep(_make_ohlcv(50), {"fast": 20}, _COST_TIERS, run_fn)
    assert "cost_survives_through" in out
    assert "tier_results" in out
    assert set(out["tier_results"].keys()) == set(_COST_TIERS.keys())


def test_run_cost_sweep_merges_cost_params():
    seen_params: list[dict] = []

    def _capture(df, params):
        seen_params.append(dict(params))
        return _fake_result(1.2, total_trades=3)

    run_cost_sweep(_make_ohlcv(50), {"fast": 20}, _COST_TIERS, _capture)
    # Each call should carry commission + slippage_ticks merged in
    for p in seen_params:
        assert "commission" in p
        assert "slippage_ticks" in p
        assert p["fast"] == 20  # champion param preserved


def test_run_cost_sweep_last_surviving_tier():
    # optimistic passes, realistic fails → cost_survives_through = optimistic
    call_count = [0]

    def _run(df, params):
        call_count[0] += 1
        pf = 1.5 if params["commission"] <= 0.31 else 0.7
        return _fake_result(pf, total_trades=5)

    out = run_cost_sweep(_make_ohlcv(50), {"fast": 20}, _COST_TIERS, _run)
    assert out["cost_survives_through"] == "optimistic"


# ---------------------------------------------------------------------------
# compute_gate_v2
# ---------------------------------------------------------------------------


def _make_oos_results(
    n: int, pf: float = 1.5, dd: float = -0.02, sharpe: float = 1.0, trades: int = 10
) -> list[OOSResult]:
    return [
        OOSResult(
            window_idx=i,
            best_params={"fast": 20},
            profit_factor=pf,
            max_drawdown_pct=dd,
            sharpe_ratio=sharpe,
            total_trades=trades,
        )
        for i in range(n)
    ]


def test_compute_gate_v2_has_required_keys():
    oos = _make_oos_results(5)
    fixed = {"fixed_params_min_pf": 1.3, "fixed_params_mean_pf": 1.5, "fixed_params_max_pf": 1.8}
    cost = {"cost_survives_through": "realistic", "tier_results": {}}
    out = compute_gate_v2(oos, n_grid_combos=5, fixed_params_metrics=fixed, cost_sweep_metrics=cost)
    required = {
        "verdict",
        "passed_via",
        "core_verdict",
        "alt_verdict",
        "pf_ci_lower",
        "p_edge",
        "mc_95th_dd_pct",
        "dsr",
        "wfo_consistency",
        "n_oos_windows",
        "n_oos_windows_with_trades",
        "total_oos_trades",
        "core_reasons",
        "alt_reasons",
    }
    assert required.issubset(out.keys())


def test_compute_gate_v2_fail_when_all_windows_lose():
    # All OOS windows have PF < 1 → p_edge = 0 → core and alt fail
    oos = _make_oos_results(10, pf=0.7, sharpe=-0.5)
    fixed = {"fixed_params_min_pf": 0.5, "fixed_params_mean_pf": 0.6, "fixed_params_max_pf": 0.8}
    cost = {"cost_survives_through": "none", "tier_results": {}}
    out = compute_gate_v2(oos, n_grid_combos=5, fixed_params_metrics=fixed, cost_sweep_metrics=cost)
    assert out["verdict"] == "FAIL"
    assert out["passed_via"] is None
    assert out["p_edge"] == pytest.approx(0.0)


def test_compute_gate_v2_empty_oos_results():
    fixed = {"fixed_params_min_pf": 0.0}
    cost = {"cost_survives_through": "none"}
    out = compute_gate_v2([], n_grid_combos=1, fixed_params_metrics=fixed, cost_sweep_metrics=cost)
    assert out["verdict"] == "FAIL"
    assert out["n_oos_windows"] == 0
    assert out["total_oos_trades"] == 0


def test_compute_gate_v2_core_reasons_tags_fail_on_mc_dd_breach():
    # pf_ci_lower/p_edge/dsr all comfortably pass; only mc_95th_dd (10% > 5% core
    # ceiling) fails. core_reasons[2] must be FAIL-tagged and n_core_passed must
    # count only 3 of 4 -- not 4, which is what an untagged f-string silently
    # produces regardless of the actual comparison result.
    oos = _make_oos_results(20, pf=2.0, dd=0.10, sharpe=2.0, trades=50)
    fixed = {"fixed_params_min_pf": 1.3, "fixed_params_mean_pf": 1.5, "fixed_params_max_pf": 1.8}
    cost = {"cost_survives_through": "realistic", "tier_results": {}}
    out = compute_gate_v2(oos, n_grid_combos=5, fixed_params_metrics=fixed, cost_sweep_metrics=cost)
    assert out["core_verdict"] == "FAIL"
    assert out["core_reasons"][2].startswith("FAIL")
    assert out["n_core_passed"] == 3


def test_compute_gate_v2_core_reasons_tags_fail_on_dsr_breach():
    # pf_ci_lower/p_edge/mc_95th_dd all pass; only dsr (near-zero, near-flat
    # sharpe) fails. core_reasons[3] must be FAIL-tagged and n_core_passed must
    # count only 3 of 4.
    oos = _make_oos_results(20, pf=1.5, dd=0.02, sharpe=0.05, trades=50)
    fixed = {"fixed_params_min_pf": 1.3, "fixed_params_mean_pf": 1.5, "fixed_params_max_pf": 1.8}
    cost = {"cost_survives_through": "realistic", "tier_results": {}}
    out = compute_gate_v2(oos, n_grid_combos=5, fixed_params_metrics=fixed, cost_sweep_metrics=cost)
    assert out["core_verdict"] == "FAIL"
    assert out["core_reasons"][3].startswith("FAIL")
    assert out["n_core_passed"] == 3


# ---------------------------------------------------------------------------
# run_wfo end-to-end (synthetic data, real Backtester + signals)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _wfo_e2e_output():
    """Run the full WFO on 500 synthetic bars once; share across all E2E tests."""
    from backtest.backtester import Backtester
    from backtest.trend_signals import generate_sma_trend_signals

    df = _make_ohlcv(500, seed=42)
    SYMBOL = "SYN"
    MULTIPLIER = 5.0
    CAPITAL = 50_000.0
    COMMISSION = 0.62
    SLIPPAGE = 2.0

    def _run_fn(df_: pd.DataFrame, params: dict) -> object:
        commission = params.get("commission", COMMISSION)
        slippage_ticks = params.get("slippage_ticks", SLIPPAGE)
        sig = generate_sma_trend_signals(
            df_,
            fast=params["fast"],
            slow=params["slow"],
        )
        bt = Backtester(
            initial_capital=CAPITAL,
            commission_per_contract=commission,
            slippage_ticks=slippage_ticks,
        )
        return bt.run(sig, symbol=SYMBOL, multiplier=MULTIPLIER)

    grid = [
        {"fast": 20, "slow": 50},
        {"fast": 30, "slow": 80},
        {"fast": 40, "slow": 120},
    ]
    cfg = WFOConfig(train_len=150, test_len=50, step_len=50)
    oos_results, window_records = run_wfo(df, grid, _run_fn, cfg)
    return oos_results, window_records


def test_run_wfo_produces_windows(_wfo_e2e_output):
    oos_results, window_records = _wfo_e2e_output
    # 500 bars, train=150, test=50, step=50: 3 windows possible
    assert len(window_records) >= 1


def test_run_wfo_window_records_have_required_keys(_wfo_e2e_output):
    _, window_records = _wfo_e2e_output
    required = {
        "window",
        "best_params",
        "is_pf",
        "is_trades",
        "oos_pf",
        "oos_dd",
        "oos_sharpe",
        "oos_trades",
    }
    for rec in window_records:
        assert required.issubset(rec.keys())


def test_run_wfo_oos_results_are_oos_result_instances(_wfo_e2e_output):
    oos_results, _ = _wfo_e2e_output
    for r in oos_results:
        assert isinstance(r, OOSResult)


def test_run_wfo_oos_pf_non_negative(_wfo_e2e_output):
    oos_results, _ = _wfo_e2e_output
    for r in oos_results:
        assert r.profit_factor >= 0.0


def test_run_wfo_best_params_from_grid(_wfo_e2e_output):
    oos_results, _ = _wfo_e2e_output
    valid = [{"fast": 20, "slow": 50}, {"fast": 30, "slow": 80}, {"fast": 40, "slow": 120}]
    for r in oos_results:
        assert r.best_params in valid


def test_run_wfo_empty_when_df_too_short():
    df = _make_ohlcv(10)
    cfg = WFOConfig(train_len=100, test_len=50, step_len=50)
    oos_results, window_records = run_wfo(
        df, [{"fast": 20, "slow": 50}], lambda d, p: _fake_result(), cfg
    )
    assert oos_results == []
    assert window_records == []
