"""Strategy C+ — lookahead guard, v1 vol-targeting legacy parity, and monitor triggers.

Pins three properties from the 2026-09-27/28 audit:
  1. The shared VolatilityTargeter's DEFAULTS reproduce the pre-audit master formula
     exactly (v1 live_signal constructs it with defaults, so any drift here changes
     paper orders). Includes the 2026-05-06 NaN guard.
  2. Both engines lag overlays by one week in backtests by default.
  3. signal_monitor triggers fire / stay quiet on the calibrated cases.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SC = Path(__file__).resolve().parents[1] / "strategy_c"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


vt_mod = _load("_sc_vol_targeting", SC / "vol_targeting.py")
mon = _load("_sc_signal_monitor", SC / "signal_monitor.py")


def _master_reference_vol(es, nq, as_of, lookback=10, floor=6.0, blend=0.60):
    """Verbatim arithmetic of master's compute_realized_vol before the audit."""
    es = es.loc[:as_of].tail(lookback + 1)
    nq = nq.loc[:as_of].tail(lookback + 1)
    if len(es) < 3 or len(nq) < 3:
        return max(floor, 15.0)
    es_ret = np.log(es / es.shift(1)).dropna()
    nq_ret = np.log(nq / nq.shift(1)).dropna()
    ann = np.sqrt(252)
    es_vol = float(es_ret.tail(lookback).std() * ann * 100)
    nq_vol = float(nq_ret.tail(lookback).std() * ann * 100)
    v = blend * nq_vol + (1 - blend) * es_vol
    if np.isnan(v) or v <= 0:
        return max(floor, 15.0)
    return max(v, floor)


def _prices(seed: int, n: int = 400, nan_idx=()):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=n)
    es = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx)
    nq = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.014, n))), index=idx)
    for i in nan_idx:
        es.iloc[i] = np.nan
    return es, nq


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("nan_idx", [(), (395,), (390, 391, 392, 393, 394, 395, 396, 397, 398)])
def test_default_vol_targeter_matches_master_formula(seed, nan_idx):
    es, nq = _prices(seed, nan_idx=nan_idx)
    vt = vt_mod.VolatilityTargeter(vol_target=8.0, lookback_days=10, vol_floor=6.0)
    for as_of in es.index[[5, 50, 200, -1]]:
        got = vt.compute_realized_vol(es, nq, as_of)
        want = _master_reference_vol(es, nq, as_of, blend=vt.blend_es_nq)
        assert got == pytest.approx(want, rel=0, abs=1e-12), (as_of, got, want)


def test_nan_vol_never_yields_full_exposure():
    idx = pd.bdate_range("2024-01-01", periods=30)
    es = pd.Series(np.nan, index=idx)
    vt = vt_mod.VolatilityTargeter(vol_target=8.0, lookback_days=10, vol_floor=6.0)
    scale, rv = vt.compute_scale(es, es, idx[-1])
    assert rv == 15.0 and scale == pytest.approx(8.0 / 15.0)
    vt2 = vt_mod.VolatilityTargeter(
        vol_target=7.0, lookback_days=5, vol_floor=6.0, blend_fast_weight=0.4, winsorize_sigma=3.0
    )
    scale2, rv2 = vt2.compute_scale(es, es, idx[-1])
    assert np.isfinite(scale2) and scale2 < 1.0


def test_engines_lag_overlays_by_default():
    src_v1 = (SC / "engine.py").read_text()
    src_v2 = (SC / "engine_v2.py").read_text()
    assert "overlay_lag_weeks: int = 1" in src_v1
    assert "vol_scale.shift(lag)" in src_v1
    assert "overlay_lag_weeks" in src_v2


# ── monitor ──────────────────────────────────────────────────────────────────
BASE = {
    "priors": {"combined_scale": {"p2_5": 0.0829, "p97_5": 1.1}},
    "wow_abs_threshold": 0.4506,
}


def _sig(
    scale=0.6,
    rv=14.0,
    vol_regime="NORMAL",
    vix=15.0,
    vix_regime="NORMAL",
    regime="RISK_ON",
    week_of=None,
    holdings=None,
):
    wk = week_of or mon.expected_signal_friday()
    return {
        "effective_date": (wk + timedelta(days=3)).isoformat(),
        "combined_scale": scale,
        "holdings": holdings or {"XLK": scale / 2, "XLV": scale / 2, "SHY": 1 - scale},
        "layers": {
            "momentum_signal": {"risk_regime": regime},
            "vol_targeting": {
                "scale": scale,
                "realized_vol_pct": rv,
                "vol_target_pct": 8.0,
                "vol_regime": vol_regime,
            },
            "vix_composite": {"vix": vix, "vix_regime": vix_regime, "fear_score": 0.9},
            "macro_filter": {"multiplier": 1.0},
        },
    }


def _ev(sig, history=()):
    return mon.evaluate(sig, BASE, list(history), "check")


def test_healthy_signal_is_quiet_even_with_high_fear():
    r = _ev(_sig())
    assert r["critical"] == [] and r["warning"] == []


def test_crisis_with_compressed_scale_is_info_only():
    r = _ev(_sig(scale=0.2, rv=40.0, vol_regime="CRISIS"))
    assert r["critical"] == [] and any("correctly compressed" in m for m in r["info"])


def test_crisis_without_compression_is_critical():
    r = _ev(_sig(scale=0.9, rv=40.0, vol_regime="CRISIS"))
    assert any("not compressing" in m for m in r["critical"])


def test_t2_judges_vol_layer_not_combined_scale():
    # vol layer failed (0.9) but a VIX multiplier dragged combined scale to 0.2
    sig = _sig(scale=0.2, rv=40.0, vol_regime="CRISIS")
    sig["layers"]["vol_targeting"]["scale"] = 0.9
    assert any("not compressing" in m for m in _ev(sig)["critical"])


def test_premarket_delivery_failure_exits_4(tmp_path, monkeypatch):
    import json as _json

    files = {
        n: tmp_path / f"{n}.json"
        for n in ("SIGNAL_FILE", "STATE_FILE", "BASELINE_FILE", "HISTORY_FILE")
    }
    files["SIGNAL_FILE"].write_text(_json.dumps(_sig(week_of=mon.expected_signal_friday())))
    files["BASELINE_FILE"].write_text(_json.dumps(BASE))
    for n, p in files.items():
        monkeypatch.setattr(mon, n, p)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)  # CI sets it; test delivery path
    monkeypatch.setattr(mon, "post_discord", lambda embed: False)
    monkeypatch.setattr(sys, "argv", ["signal_monitor.py", "--mode", "premarket"])
    assert mon.main() == 4


def test_wow_threshold_calibrated():
    lf = mon.expected_signal_friday()
    prev = mon.flat(_sig(scale=0.60, week_of=lf - timedelta(days=7)))
    assert _ev(_sig(scale=0.90), [prev])["warning"] == []  # Δ0.30: normal for v1
    assert any("Scale" in m for m in _ev(_sig(scale=0.10), [prev])["warning"])  # Δ-0.50


def test_stale_signal_is_critical():
    r = _ev(_sig(week_of=mon.expected_signal_friday() - timedelta(days=14)))
    assert any("did not run" in m for m in r["critical"])


def test_low_band_breach_warns():
    assert any("outside" in m for m in _ev(_sig(scale=0.05))["warning"])


def test_last_friday_is_friday():
    assert mon.last_friday(date(2026, 9, 28)) == date(2026, 9, 25)


# ── PR #960 review regressions ───────────────────────────────────────────────
def test_friday_before_generation_expects_prior_friday():
    from datetime import datetime, timezone

    fri_evening = datetime(2026, 9, 25, 23, 30, tzinfo=timezone.utc)
    sat_early = datetime(2026, 9, 26, 2, 0, tzinfo=timezone.utc)  # generation still landing
    sat_ready = datetime(2026, 9, 26, 3, 0, tzinfo=timezone.utc)
    sunday = datetime(2026, 9, 27, 18, 0, tzinfo=timezone.utc)
    thursday = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    assert mon.expected_signal_friday(fri_evening) == date(2026, 9, 18)
    assert mon.expected_signal_friday(sat_early) == date(2026, 9, 18)
    assert mon.expected_signal_friday(sat_ready) == date(2026, 9, 25)
    assert mon.expected_signal_friday(sunday) == date(2026, 9, 25)
    assert mon.expected_signal_friday(thursday) == date(2026, 9, 25)


def test_failed_delivery_does_not_advance_fingerprint(tmp_path, monkeypatch):
    import json as _json

    sig_file, state_file = tmp_path / "sig.json", tmp_path / "state.json"
    base_file, hist_file = tmp_path / "base.json", tmp_path / "hist.json"
    sig_file.write_text(
        _json.dumps(_sig(week_of=mon.expected_signal_friday() - timedelta(days=21)))
    )
    base_file.write_text(_json.dumps(BASE))
    for name, p in (
        ("SIGNAL_FILE", sig_file),
        ("STATE_FILE", state_file),
        ("BASELINE_FILE", base_file),
        ("HISTORY_FILE", hist_file),
    ):
        monkeypatch.setattr(mon, name, p)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)  # CI sets it; test delivery path
    monkeypatch.setattr(mon, "post_discord", lambda embed: False)
    monkeypatch.setattr(sys, "argv", ["signal_monitor.py", "--mode", "check"])
    assert mon.main() == 4
    assert not state_file.exists()
    monkeypatch.setattr(mon, "post_discord", lambda embed: True)
    assert mon.main() == 2
    assert _json.loads(state_file.read_text())["last_severity"] == "critical"


def test_transaction_costs_charge_execution_on_turnover_only():
    tc = _load("_sc_tc", SC / "transaction_costs.py")
    m = tc.TransactionCostModel()
    small = m.estimate_portfolio_weekly_cost({"SPY": 0.51, "SHY": 0.49}, {"SPY": 0.49, "SHY": 0.51})
    hold = m.estimate_portfolio_weekly_cost({"SPY": 0.50, "SHY": 0.50}, {"SPY": 0.50, "SHY": 0.50})
    exec_rate = m.weekly_cost_rate("SPY", True) - m.weekly_cost_rate("SPY", False)
    # A 2% rebalance may add at most ~2% x (spread+slippage) per leg over holding costs
    assert (
        small["total_cost_pct"] - hold["total_cost_pct"]
        <= 0.02
        * 2
        * max(exec_rate, m.weekly_cost_rate("SHY", True) - m.weekly_cost_rate("SHY", False))
        + 1e-12
    )


def test_extreme_vix_composite_label_is_risk_off():
    src = (SC / "vix_composite.py").read_text()
    assert 'result.loc[result["vix_regime"] == "EXTREME", "composite_regime"] = "RISK_OFF"' in src


def test_missing_webhook_in_actions_is_config_error(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(mon, "DISCORD_WEBHOOK", "")
    monkeypatch.setattr(sys, "argv", ["signal_monitor.py", "--mode", "check"])
    assert mon.main() == 3


def test_crash_exits_5_not_warning(monkeypatch):
    def boom():
        raise TypeError("holdings is not a dict")

    monkeypatch.setattr(mon, "main", boom)
    assert mon.run() == 5


def test_future_dated_signal_is_critical():
    r = _ev(_sig(week_of=mon.expected_signal_friday() + timedelta(days=7)))
    assert any("future" in m for m in r["critical"])


def test_out_of_range_weight_is_critical():
    r = _ev(_sig(holdings={"XLK": 1.3, "SHY": -0.3}))
    assert any("out of range" in m for m in r["critical"])
