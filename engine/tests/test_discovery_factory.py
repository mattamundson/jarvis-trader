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
from backtest.donchian_signals import generate_donchian_signals
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


# ----------------------------------------------------- load_interval_bars (_cont)
def _write_intraday_cache(d, name: str, start: str, periods: int, freq: str) -> None:
    """Write a synthetic intraday (5m/15m) OHLCV cache with a real span."""
    idx = pd.date_range(start=start, periods=periods, freq=freq, tz="UTC")
    rows = "".join(f"{ts.isoformat()},100,101,99,100,10\n" for ts in idx)
    (d / name).write_text(_HEADER + rows, encoding="utf-8")


def test_load_interval_bars_accepts_cont_only(tmp_path):
    """A symbol whose only intraday cache is the _cont variant must still load."""
    d = tmp_path / "cache"
    d.mkdir()
    _write_intraday_cache(d, "MGC_2024-05-01_2026-05-29_5m_cont.csv", "2024-05-01", 500, "5min")
    df = dfac.load_interval_bars("MGC", "5m", d)
    assert len(df) == 500
    assert df.attrs["source_file"] == "MGC_2024-05-01_2026-05-29_5m_cont.csv"


def test_load_interval_bars_freshest_end_date_wins(tmp_path):
    """Across bare and _cont, the freshest end-date wins (bare here is fresher)."""
    d = tmp_path / "cache"
    d.mkdir()
    _write_intraday_cache(d, "MES_2025-04-09_2026-06-12_5m_cont.csv", "2025-04-09", 300, "5min")
    _write_intraday_cache(d, "MES_2025-04-09_2026-06-22_5m.csv", "2025-04-09", 400, "5min")
    df = dfac.load_interval_bars("MES", "5m", d)
    assert df.attrs["source_file"] == "MES_2025-04-09_2026-06-22_5m.csv"


def test_load_interval_bars_prefers_cont_on_tie(tmp_path):
    """On an exact end-date tie, the roll-adjusted _cont file is preferred."""
    d = tmp_path / "cache"
    d.mkdir()
    _write_intraday_cache(d, "MNQ_2025-04-09_2026-06-12_5m.csv", "2025-04-09", 300, "5min")
    _write_intraday_cache(d, "MNQ_2025-04-09_2026-06-12_5m_cont.csv", "2025-04-09", 350, "5min")
    df = dfac.load_interval_bars("MNQ", "5m", d)
    assert df.attrs["source_file"] == "MNQ_2025-04-09_2026-06-12_5m_cont.csv"


def test_load_interval_bars_missing_raises(tmp_path):
    """No bare and no _cont cache -> FileNotFoundError (plan_spec maps to NO_CACHE)."""
    d = tmp_path / "cache"
    d.mkdir()
    with pytest.raises(FileNotFoundError):
        dfac.load_interval_bars("MES", "5m", d)


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


def test_intraday_frontier_specs_registered():
    """The 5m + new-15m intraday frontier is registered across MES/MGC/MNQ."""
    reg = default_registry()
    labels = {s.label for s in reg}
    for sym in ("MES", "MGC", "MNQ"):
        assert f"{sym}_sma_trend_5m" in labels, f"missing {sym} 5m trend"
    for sym in ("MGC", "MNQ"):
        assert f"{sym}_bollinger_rsi_15m" in labels, f"missing {sym} 15m meanrev"
    # The frontier = the simple-family + ORB sweep (rv_filter specs are tagged
    # 'intraday' too but not 'frontier', so scope to 'frontier' to stay stable).
    frontier = [s for s in reg if "frontier" in s.tags]
    # 5 (symbol, interval) pairs x 4 families + 3 ORB specs.
    assert len(frontier) == 23
    assert all(s.min_oos_trades_per_window == 3 for s in frontier)
    assert all(s.symbol in CONTRACT_SPECS for s in frontier)


def test_rv_filtered_trend_specs_registered():
    """RV-filtered trend specs carry an RV grid + interval-correct annual factor."""
    from backtest.discovery_factory import _RV_ANNUAL_FACTOR_BY_INTERVAL

    reg = default_registry()
    # The intraday rv extension = rv_filter-tagged AND intraday (the existing 1h
    # regime-filter probes are rv_filter-tagged but not 'intraday').
    rv = [s for s in reg if "rv_filter" in s.tags and "intraday" in s.tags]
    assert len(rv) == 4
    assert {s.label for s in rv} == {
        "MGC_sma_trend_rv_5m",
        "MGC_sma_trend_rv_15m",
        "MES_sma_trend_rv_5m",
        "MES_sma_trend_rv_15m",
    }
    # No collision with the existing *_rv_1h specs.
    assert all(not s.label.endswith("_rv_1h") for s in rv)
    for s in rv:
        rvs = {c["min_rv_annualized"] for c in s.param_grid}
        assert all(v > 0.0 for v in rvs) and len(rvs) >= 2, "every combo enables the RV gate"
        factors = {c["rv_annual_factor"] for c in s.param_grid}
        assert factors == {_RV_ANNUAL_FACTOR_BY_INTERVAL[s.interval]}, "wrong annualization factor"
        assert s.min_oos_trades_per_window == 3


def test_drawdown_attack_specs_registered():
    """DD specs use the robust slow in {48,72} grid + a lowered risk_per_trade."""
    reg = default_registry()
    dd = [s for s in reg if "drawdown_attack" in s.tags and "donchian" not in s.tags]
    assert {s.label for s in dd} == {
        "MGC_sma_trend_dd_5m",
        "MGC_sma_trend_dd_15m",
        "MGC_sma_trend_dd_lo_5m",
        "MGC_sma_trend_dd_mid_5m",
    }
    by_label = {s.label: s for s in dd}
    # Three 5m risk levels probe the dsr/drawdown tradeoff: 0.005 / 0.0035 / 0.0025.
    assert by_label["MGC_sma_trend_dd_lo_5m"].risk_per_trade == 0.0025
    assert by_label["MGC_sma_trend_dd_mid_5m"].risk_per_trade == 0.0035
    assert by_label["MGC_sma_trend_dd_5m"].risk_per_trade == 0.005
    for s in dd:
        assert s.risk_per_trade <= 0.005, "must size down to fit the drawdown budget"
        slows = {c["slow"] for c in s.param_grid}
        assert slows == {48, 72}, "robust grid excludes the whipsaw slow=24 region"
        assert all(c["fast"] in (12, 16, 20) for c in s.param_grid)
        assert s.min_oos_trades_per_window == 3


def test_position_stop_attack_specs_registered():
    """Lever 2: tighter per-trade stop at FULL risk (0.01) -- not sizing-tuned.

    These attack drawdown at the position level (tighter atr_trail_mult) and must
    keep risk_per_trade=0.01 and NOT carry the drawdown_attack tag (so the
    synthesizer's sizing-tuned fragility flag does not fire on them)."""
    reg = default_registry()
    stop = [s for s in reg if "stop_attack" in s.tags]
    by_label = {s.label: s for s in stop}
    assert set(by_label) == {"MGC_sma_trend_stop_5m", "MGC_donchian_stop_15m"}
    for s in stop:
        assert s.risk_per_trade == 0.01, "full risk -- no global size cut"
        assert "drawdown_attack" not in s.tags
        assert s.min_oos_trades_per_window == 3
        atrs = {c["atr_trail_mult"] for c in s.param_grid}
        # grid must reach into the tighter (<1.5) region the baseline never tested
        assert min(atrs) <= 1.25, "must force evaluation of tight stops"
    # trend keeps the robust slow region; donchian keeps the baseline lookbacks
    trend = by_label["MGC_sma_trend_stop_5m"]
    assert {c["slow"] for c in trend.param_grid} == {48, 72}
    assert trend.signal_fn is generate_sma_trend_signals
    don = by_label["MGC_donchian_stop_15m"]
    assert don.signal_fn is generate_donchian_signals


def test_donchian_drawdown_attack_band_registered():
    """Donchian dd specs sweep a risk BAND on the baseline (robust) donchian grid.

    The robustness test for the cleanest non-blocked near-miss: a genuine PASS
    must hold across the whole 0.004/0.005/0.006 band, not at one knife-edge size.
    """
    reg = default_registry()
    don = [s for s in reg if "drawdown_attack" in s.tags and "donchian" in s.tags]
    by_label = {s.label: s for s in don}
    assert set(by_label) == {
        "MGC_donchian_dd_lo_15m",
        "MGC_donchian_dd_15m",
        "MGC_donchian_dd_hi_15m",
    }
    assert by_label["MGC_donchian_dd_lo_15m"].risk_per_trade == 0.004
    assert by_label["MGC_donchian_dd_15m"].risk_per_trade == 0.005
    assert by_label["MGC_donchian_dd_hi_15m"].risk_per_trade == 0.006
    for s in don:
        assert s.signal_fn is generate_donchian_signals
        # baseline donchian grid -- fixed_params_min_pf already 2.38, no surgery
        entries = {c["lookback_entry"] for c in s.param_grid}
        exits = {c["lookback_exit"] for c in s.param_grid}
        assert entries == {20, 40} and exits == {10, 20}
        assert s.min_oos_trades_per_window == 3


def test_spec_risk_per_trade_routes_to_backtester(monkeypatch):
    """_make_run_fn must pass spec.risk_per_trade to the Backtester (not a constant)."""
    import backtest.discovery_factory as m

    captured = {}

    class _FakeResult:
        pass

    class _FakeBT:
        def __init__(self, **kw):
            captured.update(kw)

        def run(self, *a, **k):
            return _FakeResult()

    # _make_run_fn does `from backtest.backtester import Backtester` locally,
    # so patch it at the source module, not on discovery_factory.
    monkeypatch.setattr("backtest.backtester.Backtester", _FakeBT)
    spec = StrategySpec(
        symbol="MGC",
        family="sma_trend_dd",
        interval="5m",
        signal_fn=lambda df, **k: df,
        param_grid=grid(fast=[12]),
        train_months=3,
        risk_per_trade=0.005,
    )
    run_fn = m._make_run_fn(spec)
    run_fn(pd.DataFrame({"close": [1.0]}), {"fast": 12})
    assert captured["risk_per_trade"] == 0.005


def _orb_frame(days=("2026-03-02", "2026-03-03"), freq="15min"):
    """Synthetic ET-localized intraday frame with a rising price (triggers longs)."""
    import numpy as np

    frames = []
    for d in days:
        idx = pd.date_range(f"{d} 09:00", f"{d} 15:45", freq=freq, tz="America/New_York")
        base = 100.0 + np.arange(len(idx)) * 0.5
        frames.append(
            pd.DataFrame(
                {
                    "open": base,
                    "high": base + 1,
                    "low": base - 1,
                    "close": base + 0.5,
                    "volume": 100.0,
                },
                index=idx,
            )
        )
    return pd.concat(frames)


def test_orb_sub_hourly_marks_one_open_bar_per_session():
    """Sub-hourly detection marks exactly the first bar at/after 09:30 ET per day."""
    from backtest.orb_signals import _detect_rth_open_bar

    frame = _orb_frame()
    is_or = _detect_rth_open_bar(frame, sub_hourly=True)
    assert int(is_or.sum()) == 2  # one per weekday session
    et = is_or[is_or].index.tz_convert("America/New_York")
    assert all((t.hour, t.minute) == (9, 30) for t in et)


def test_orb_adapter_emits_backtester_columns():
    """Adapter maps ORB output to Backtester-native columns with correct bias/targets."""
    from backtest.orb_factory_adapter import generate_orb_factory_signals

    sig = generate_orb_factory_signals(_orb_frame(), symbol="MES", t1_range_mult=2.0)
    for col in ("entry_signal", "exit_signal", "bias", "stop_level", "target_1", "target_2"):
        assert col in sig.columns
    longs = sig[sig["bias"] == "STRONG_BULL"]
    assert len(longs) > 0, "rising price should trigger long ORB entries"
    assert (longs["entry_signal"] == "ENTRY_NOW").all()
    # T1 is 2x the OR range above the OR high (clears the Backtester R:R>=1.2 gate).
    row = longs.iloc[0]
    assert abs(row["target_1"] - (row["or_high"] + 2.0 * row["or_range"])) < 1e-6


def test_orb_specs_registered():
    labels = {s.label for s in default_registry()}
    for sym in ("MES", "MGC", "MNQ"):
        assert f"{sym}_orb_15m" in labels


def test_regime_filtered_trend_specs_registered_with_rv_axis():
    # The sma_trend_rv family must sweep a non-zero realized-vol floor on every
    # combo (that gate IS the regime filter); a zero floor would silently degrade
    # to the plain trend family and the experiment would be a no-op.
    reg = default_registry()
    rv_specs = [s for s in reg if s.family == "sma_trend_rv"]
    assert {s.symbol for s in rv_specs} == {"MGC", "MES"}
    # The family now spans 1h (baseline regime-filter probes) and intraday (the
    # 5m/15m extension); every combo must still enable the RV gate.
    assert {s.interval for s in rv_specs} <= {"1h", "5m", "15m"}
    for s in rv_specs:
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


# --- Stage 3: synthesizer -------------------------------------------------


def _write_verdict(
    d,
    label,
    verdict,
    *,
    trades,
    pf=1.5,
    p_edge=0.5,
    dsr=0.5,
    dd_pct=3.0,
    passed_via=None,
    sample_adequate=None,
    tags=(),
):
    """Dump a minimal per-spec verdict JSON the synthesizer can read."""
    sym, fam, interval = label.split("_", 1)[0], "fam", label.rsplit("_", 1)[-1]
    payload = {
        "label": label,
        "symbol": sym,
        "family": fam,
        "interval": interval,
        "verdict": verdict,
        "passed_via": passed_via,
        "tags": list(tags),
        "source_file": f"{label}.csv",
        "champion_params": {"fast": 8},
        "gate_v2": {
            "pf_ci_lower": pf,
            "p_edge": p_edge,
            "dsr": dsr,
            "mc_95th_dd_pct": dd_pct,
            "wfo_consistency": "STRONG",
            "fixed_params_min_pf": 1.3,
            "cost_survives_through": "realistic",
            "total_oos_trades": trades,
            "sample_adequate": sample_adequate,
        },
    }
    (d / f"{label}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_synth_undersampled_pass_is_not_a_candidate(tmp_path):
    from backtest.discovery_synthesize import synthesize

    # A PASS on only 5 OOS trades is noise, not an edge -- must not be briefed.
    _write_verdict(tmp_path, "MES_x_15m", "PASS", trades=5, passed_via="core")
    res = synthesize(tmp_path)
    assert res["n_pass"] == 0
    assert "Caution" in res["report"]
    assert "CANDIDATE: MES_x_15m" not in res["report"]
    assert "Honest negative" in res["report"]


def test_synth_deployable_pass_gets_a_brief(tmp_path):
    from backtest.discovery_synthesize import synthesize

    _write_verdict(tmp_path, "MGC_x_5m", "PASS", trades=120, passed_via="alt", sample_adequate=True)
    res = synthesize(tmp_path)
    assert res["n_pass"] == 1
    assert "CANDIDATE: MGC_x_5m" in res["report"]
    assert "passed_via=alt" in res["report"]


def test_synth_razor_thin_dd_pass_is_flagged_fragile(tmp_path):
    """An ALT PASS that clears the 4% DD ceiling by <0.1pp is briefed WITH a
    razor-thin-margin caution -- never as a clean candidate."""
    from backtest.discovery_synthesize import synthesize

    _write_verdict(
        tmp_path,
        "MGC_x_5m",
        "PASS",
        trades=525,
        passed_via="alt",
        dd_pct=3.997,
        sample_adequate=True,
    )
    res = synthesize(tmp_path)
    assert res["n_pass"] == 1
    assert "CANDIDATE: MGC_x_5m" in res["report"]
    assert "Razor-thin drawdown margin" in res["report"]


def test_synth_drawdown_attack_pass_is_flagged_sizing_tuned(tmp_path):
    """A drawdown_attack-tagged PASS must carry the sizing-tuned / verify-across-band
    caution even when its DD margin is comfortable."""
    from backtest.discovery_synthesize import synthesize

    _write_verdict(
        tmp_path,
        "MGC_x_5m",
        "PASS",
        trades=525,
        passed_via="alt",
        dd_pct=2.5,
        sample_adequate=True,
        tags=("intraday", "drawdown_attack", "5m"),
    )
    res = synthesize(tmp_path)
    assert res["n_pass"] == 1
    assert "Sizing-tuned pass" in res["report"]
    assert "knife-edge" in res["report"]


def test_synth_clean_pass_has_no_fragility_warning(tmp_path):
    """A comfortable CORE pass (good DD margin, not sizing-tuned) gets no caution."""
    from backtest.discovery_synthesize import synthesize

    _write_verdict(
        tmp_path,
        "MGC_x_5m",
        "PASS",
        trades=200,
        passed_via="core",
        dd_pct=1.5,
        sample_adequate=True,
    )
    res = synthesize(tmp_path)
    assert "CANDIDATE: MGC_x_5m" in res["report"]
    assert "Razor-thin drawdown margin" not in res["report"]
    assert "Sizing-tuned pass" not in res["report"]


def test_synth_blocked_symbol_candidate_is_flagged(tmp_path):
    """A PASS on a DO_NOT_TRADE symbol must be briefed with a loud block warning."""
    from backtest.discovery_synthesize import DO_NOT_TRADE, synthesize

    blocked = next(iter(DO_NOT_TRADE))  # e.g. MNQ
    _write_verdict(
        tmp_path, f"{blocked}_x_15m", "PASS", trades=186, passed_via="alt", sample_adequate=True
    )
    res = synthesize(tmp_path)
    assert res["n_pass"] == 1
    assert "DO_NOT_TRADE" in res["report"]
    assert "!DNT" in res["report"]  # table flag


def test_synth_near_miss_flagged_and_leaderboard_skipped(tmp_path):
    from backtest.discovery_synthesize import synthesize

    # FAIL but sample-adequate, PF>=1.10, DSR>=0.10 -> near-miss watchlist.
    _write_verdict(tmp_path, "MGC_x_5m", "FAIL", trades=388, pf=1.25, p_edge=0.83, dsr=0.79)
    # FAIL with no edge -> not a near-miss.
    _write_verdict(tmp_path, "MES_y_15m", "FAIL", trades=409, pf=0.73, p_edge=0.50, dsr=0.0)
    # The aggregate LEADERBOARD.json must be ignored, not parsed as a spec.
    (tmp_path / "LEADERBOARD.json").write_text(json.dumps({"ranked": []}), encoding="utf-8")
    res = synthesize(tmp_path)
    assert res["n_specs"] == 2  # LEADERBOARD.json excluded
    assert res["n_near"] == 1
