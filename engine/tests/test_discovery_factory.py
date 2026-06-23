"""
Tests for backtest.discovery_factory -- the Phase-3 config-driven sweep.

Covers the factory's OWN logic (grid expansion, spec selection, champion-param
voting, leaderboard ranking, dry-run planning against synthetic caches, and
run_spec's wiring of the canonical wfo_lifecycle pipeline + JSON output). The
gate-v2 math itself is exercised by wfo_lifecycle's own tests; here we only
verify the factory calls it correctly and never writes into gate_v2_verdicts/.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from backtest import discovery_factory as dfac
from backtest.discovery_factory import (
    CONTRACT_SPECS,
    OUTPUT_DIR,
    StrategySpec,
    _champion_params,
    _rank_verdicts,
    _select,
    default_registry,
    grid,
    plan_spec,
)
from backtest.trend_signals import generate_sma_trend_signals

_HEADER = "timestamp,open,high,low,close,volume\n"


def _write_hourly_cache(d, name: str, start: str, periods: int) -> None:
    """Write a synthetic hourly OHLCV cache with a real DatetimeIndex span."""
    idx = pd.date_range(start=start, periods=periods, freq="h", tz="UTC")
    rows = "".join(f"{ts.isoformat()},100,101,99,100,10\n" for ts in idx)
    (d / name).write_text(_HEADER + rows, encoding="utf-8")


@pytest.fixture
def cache(tmp_path):
    d = tmp_path / "cache"
    d.mkdir()
    # ~14 months of hourly bars -> enough to form several 6mo/2mo windows.
    _write_hourly_cache(d, "MGC_2024-01-01_2025-03-01_1h.csv", "2024-01-01", 24 * 425)
    _write_hourly_cache(d, "MES_2024-01-01_2025-03-01_1h.csv", "2024-01-01", 24 * 425)
    return d


# --------------------------------------------------------------------------- grid
def test_grid_cartesian_product():
    g = grid(fast=[8, 12], slow=[24, 36])
    assert g == [
        {"fast": 8, "slow": 24},
        {"fast": 8, "slow": 36},
        {"fast": 12, "slow": 24},
        {"fast": 12, "slow": 36},
    ]


def test_grid_single_axis():
    assert grid(x=[1, 2, 3]) == [{"x": 1}, {"x": 2}, {"x": 3}]


# ---------------------------------------------------------------- StrategySpec
def test_spec_label_and_combo_count():
    s = StrategySpec(
        symbol="MES",
        family="sma_trend",
        interval="15m",
        signal_fn=lambda df, **k: df,
        param_grid=grid(fast=[8, 12], slow=[24, 36]),
        train_months=3,
    )
    assert s.label == "MES_sma_trend_15m"
    assert s.n_combos == 4


def test_registry_only_supported_symbols():
    reg = default_registry()
    assert reg, "registry must not be empty"
    for s in reg:
        assert s.symbol in CONTRACT_SPECS, f"{s.label} uses unsupported symbol"


def test_regime_filtered_trend_specs_registered_with_rv_axis():
    # The sma_trend_rv family must sweep a non-zero realized-vol floor on every
    # combo (that gate IS the regime filter); a zero floor would silently degrade
    # to the plain trend family and the experiment would be a no-op.
    reg = default_registry()
    rv_specs = [s for s in reg if s.family == "sma_trend_rv"]
    assert {s.symbol for s in rv_specs} == {"MGC", "MES"}
    for s in rv_specs:
        assert s.interval == "1h"
        assert s.signal_fn is generate_sma_trend_signals
        assert "rv_filter" in s.tags
        assert all(
            c.get("min_rv_annualized", 0.0) > 0.0 for c in s.param_grid
        ), f"{s.label}: every combo must enable the RV gate"


# --------------------------------------------------------------------- _select
def test_select_filters_by_symbol_family_interval():
    reg = default_registry()
    assert all(s.symbol == "MES" for s in _select(reg, "MES", None, None))
    assert all(s.interval == "15m" for s in _select(reg, None, None, "15m"))
    only = _select(reg, "MES", "donchian", "15m")
    assert len(only) == 1 and only[0].label == "MES_donchian_15m"
    assert _select(reg, "NOPE", None, None) == []


# ------------------------------------------------------------ _champion_params
def test_champion_params_picks_most_voted():
    records = [
        {"best_params": {"fast": 8, "slow": 24}},
        {"best_params": {"fast": 8, "slow": 24}},
        {"best_params": {"fast": 12, "slow": 36}},
    ]
    assert _champion_params(records, {"fast": 99}) == {"fast": 8, "slow": 24}


def test_champion_params_fallback_when_empty():
    assert _champion_params([], {"fast": 50, "slow": 200}) == {"fast": 50, "slow": 200}


# ------------------------------------------------------------- _rank_verdicts
def test_rank_puts_pass_first_then_dsr():
    verdicts = [
        {"label": "a", "verdict": "FAIL", "gate_v2_metrics": {"dsr": 0.5, "pf_ci_lower": 1.0}},
        {"label": "b", "verdict": "PASS", "gate_v2_metrics": {"dsr": 0.2, "pf_ci_lower": 1.2}},
        {"label": "c", "verdict": "PASS", "gate_v2_metrics": {"dsr": 0.9, "pf_ci_lower": 1.5}},
        {"label": "d", "verdict": "NO_WINDOWS"},
    ]
    ranked = [v["label"] for v in _rank_verdicts(verdicts)]
    # PASS by descending dsr (c then b), then FAIL (a), then NO_WINDOWS (d).
    assert ranked == ["c", "b", "a", "d"]


# ------------------------------------------------------------------ plan_spec
def test_plan_spec_ready_counts_windows(cache):
    spec = _select(default_registry(), "MGC", "sma_trend", "1h")[0]
    p = plan_spec(spec, cache)
    assert p["status"] == "READY"
    assert p["n_windows"] > 0
    assert p["n_combos"] == spec.n_combos
    assert p["approx_backtests"] > p["n_combos"]
    assert p["source_file"] == "MGC_2024-01-01_2025-03-01_1h.csv"


def test_plan_spec_missing_cache(cache):
    # 15m cache is absent in the fixture -> NO_CACHE, not a crash.
    spec = _select(default_registry(), "MES", "sma_trend", "15m")[0]
    p = plan_spec(spec, cache)
    assert p["status"] == "NO_CACHE"


def test_plan_spec_unsupported_symbol(cache):
    spec = StrategySpec(
        symbol="ZZZ",
        family="sma_trend",
        interval="1h",
        signal_fn=lambda df, **k: df,
        param_grid=grid(fast=[8]),
        train_months=3,
    )
    assert plan_spec(spec, cache)["status"] == "UNSUPPORTED_SYMBOL"


# ------------------------------------------------------------------- run_spec
def test_run_spec_wires_pipeline_and_writes_json(cache, monkeypatch, tmp_path):
    """run_spec must call the canonical pipeline and persist to discovery_factory/,
    NOT gate_v2_verdicts/. We stub the heavy wfo_lifecycle calls."""
    spec = _select(default_registry(), "MGC", "sma_trend", "1h")[0]

    fake_oos = [object()]
    fake_records = [{"best_params": {"fast": 40, "slow": 100, "atr_trail_mult": 1.5}}]
    fake_gate = {
        "verdict": "PASS",
        "passed_via": "alt",
        "pf_ci_lower": 1.2,
        "p_edge": 1.0,
        "mc_95th_dd": 0.03,
        "mc_95th_dd_pct": 3.0,
        "dsr": 0.4,
        "wfo_consistency": "STRONG",
        "fixed_params_min_pf": 1.3,
        "cost_survives_through": "pessimistic",
        "n_oos_windows": 5,
        "n_oos_windows_with_trades": 5,
        "total_oos_trades": 60,
        "core_reasons": [],
        "alt_reasons": [],
        "reasons": [],
    }
    monkeypatch.setattr(dfac, "_make_run_fn", lambda s: (lambda df, p: None))
    monkeypatch.setattr(dfac, "run_wfo", lambda *a, **k: (fake_oos, fake_records))
    monkeypatch.setattr(
        dfac, "run_fixed_params_sweep", lambda *a, **k: {"fixed_params_min_pf": 1.3}
    )
    monkeypatch.setattr(
        dfac, "run_cost_sweep", lambda *a, **k: {"cost_survives_through": "pessimistic"}
    )
    monkeypatch.setattr(dfac, "compute_gate_v2", lambda *a, **k: fake_gate)
    out_dir = tmp_path / "discovery_out"
    monkeypatch.setattr(dfac, "OUTPUT_DIR", out_dir)

    v = dfac.run_spec(spec, cache)

    assert v["verdict"] == "PASS"
    assert v["champion_params"] == {"fast": 40, "slow": 100, "atr_trail_mult": 1.5}
    assert v["gate_v2_metrics"]["total_oos_trades"] == 60
    written = out_dir / "MGC_sma_trend_1h.json"
    assert written.exists()
    json.loads(written.read_text())  # must be valid JSON
    # Critical safety invariant: discovery never writes to the live tradeability store.
    assert "gate_v2_verdicts" not in str(out_dir)


def test_run_spec_no_windows_returns_sentinel(cache, monkeypatch):
    spec = _select(default_registry(), "MGC", "sma_trend", "1h")[0]
    monkeypatch.setattr(dfac, "_make_run_fn", lambda s: (lambda df, p: None))
    monkeypatch.setattr(dfac, "run_wfo", lambda *a, **k: ([], []))
    v = dfac.run_spec(spec, cache)
    assert v["verdict"] == "NO_WINDOWS"


def test_run_spec_below_sample_floor_overrides_to_insufficient(cache, monkeypatch, tmp_path):
    """A gate that scores PASS but on < MIN_OOS_TRADES_TOTAL total OOS trades MUST
    be overridden to INSUFFICIENT_SAMPLE -- compute_gate_v2 grades edge metrics but
    does NOT gate on sample size, so a handful of trades in one window can spuriously
    PASS. This mirrors run_cl_trend_rank1.py's sample-adequacy override and is the
    fix for the real MES_rsi_breakout_15m false-positive (5 trades in 1 window)."""
    spec = _select(default_registry(), "MGC", "sma_trend", "1h")[0]
    thin_gate = {
        "verdict": "PASS",
        "passed_via": "core",
        "pf_ci_lower": 1.48,
        "p_edge": 1.0,
        "mc_95th_dd": 0.003,
        "mc_95th_dd_pct": 0.29,
        "dsr": 0.97,
        "wfo_consistency": "STRONG",
        "fixed_params_min_pf": 0.34,
        "cost_survives_through": "catastrophic",
        "n_oos_windows": 6,
        "n_oos_windows_with_trades": 1,
        "total_oos_trades": 5,
        "core_reasons": [],
        "alt_reasons": [],
        "reasons": [],
    }
    monkeypatch.setattr(dfac, "_make_run_fn", lambda s: (lambda df, p: None))
    monkeypatch.setattr(
        dfac,
        "run_wfo",
        lambda *a, **k: ([object()], [{"best_params": spec.param_grid[0]}]),
    )
    monkeypatch.setattr(
        dfac, "run_fixed_params_sweep", lambda *a, **k: {"fixed_params_min_pf": 0.34}
    )
    monkeypatch.setattr(
        dfac, "run_cost_sweep", lambda *a, **k: {"cost_survives_through": "catastrophic"}
    )
    # Return a fresh copy so the override can't mutate shared test state.
    monkeypatch.setattr(dfac, "compute_gate_v2", lambda *a, **k: dict(thin_gate))
    monkeypatch.setattr(dfac, "OUTPUT_DIR", tmp_path / "out")

    v = dfac.run_spec(spec, cache)

    assert v["verdict"] == "INSUFFICIENT_SAMPLE"
    assert v["passed_via"] is None
    assert v["gate_v2_metrics"]["total_oos_trades"] == 5
    assert v["gate_v2"]["sample_adequate"] is False


def test_run_spec_at_sample_floor_keeps_pass(cache, monkeypatch, tmp_path):
    """A genuine PASS with >= MIN_OOS_TRADES_TOTAL trades is untouched by the floor."""
    spec = _select(default_registry(), "MGC", "sma_trend", "1h")[0]
    ok_gate = {
        "verdict": "PASS",
        "passed_via": "alt",
        "pf_ci_lower": 1.2,
        "p_edge": 1.0,
        "mc_95th_dd": 0.03,
        "mc_95th_dd_pct": 3.0,
        "dsr": 0.4,
        "wfo_consistency": "STRONG",
        "fixed_params_min_pf": 1.3,
        "cost_survives_through": "pessimistic",
        "n_oos_windows": 8,
        "n_oos_windows_with_trades": 8,
        "total_oos_trades": 45,
        "core_reasons": [],
        "alt_reasons": [],
        "reasons": [],
    }
    monkeypatch.setattr(dfac, "_make_run_fn", lambda s: (lambda df, p: None))
    monkeypatch.setattr(
        dfac,
        "run_wfo",
        lambda *a, **k: ([object()], [{"best_params": spec.param_grid[0]}]),
    )
    monkeypatch.setattr(
        dfac, "run_fixed_params_sweep", lambda *a, **k: {"fixed_params_min_pf": 1.3}
    )
    monkeypatch.setattr(
        dfac, "run_cost_sweep", lambda *a, **k: {"cost_survives_through": "pessimistic"}
    )
    monkeypatch.setattr(dfac, "compute_gate_v2", lambda *a, **k: dict(ok_gate))
    monkeypatch.setattr(dfac, "OUTPUT_DIR", tmp_path / "out")

    v = dfac.run_spec(spec, cache)

    assert v["verdict"] == "PASS"
    assert v["gate_v2"]["sample_adequate"] is True


def test_output_dir_is_not_gate_v2_verdicts():
    # Hard guard at import time: the discovery store must be distinct from the
    # live engine's verdict store, so a candidate can't silently authorize trading.
    assert OUTPUT_DIR.name == "discovery_factory"
    assert "gate_v2_verdicts" not in str(OUTPUT_DIR)
