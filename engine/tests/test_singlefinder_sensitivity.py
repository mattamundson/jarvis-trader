"""Tests for the singlefinder sensitivity driver (backtest/singlefinder_sensitivity.py).

Covers the two pure, isolatable helpers (no backtest/cache machinery):
  - _metrics_from_result: BacktestResult-shape -> metrics dict (None / empty / PF cap)
  - subperiod_stability: per-window OOS PF dispersion from a synthetic verdict JSON,
    incl. the fail-open None handling (None drops from the stability series but still
    counts toward n / p_edge denominator).

Read-only analysis module; not on the trading path.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from backtest import singlefinder_sensitivity as sfs

# --- _metrics_from_result --------------------------------------------------


def test_metrics_from_result_none_is_zeroed():
    assert sfs._metrics_from_result(None) == {
        "pf": 0.0,
        "trades": 0,
        "sharpe": 0.0,
        "return": 0.0,
        "win_rate": 0.0,
    }


def test_metrics_from_result_no_trades_is_zeroed():
    r = SimpleNamespace(total_trades=0)
    assert sfs._metrics_from_result(r)["trades"] == 0
    assert sfs._metrics_from_result(r)["pf"] == 0.0


def test_metrics_from_result_populated_rounds_and_scales():
    r = SimpleNamespace(
        total_trades=10,
        profit_factor=1.234567,
        sharpe_ratio=2.1,
        total_return_pct=0.05,  # fraction -> *100 -> 5.0%
        win_rate=0.42,  # fraction -> *100 -> 42.0%
    )
    m = sfs._metrics_from_result(r)
    assert m == {"pf": 1.235, "trades": 10, "sharpe": 2.1, "return": 5.0, "win_rate": 42.0}


def test_metrics_from_result_caps_profit_factor_at_999():
    r = SimpleNamespace(
        total_trades=5,
        profit_factor=1500.0,  # capped
        sharpe_ratio=3.0,
        total_return_pct=1.0,
        win_rate=0.9,
    )
    assert sfs._metrics_from_result(r)["pf"] == 999.0


# --- subperiod_stability ---------------------------------------------------


def _write_verdict(tmp_path, oos_pfs):
    p = tmp_path / "v.json"
    p.write_text(json.dumps({"windows": [{"oos_pf": v} for v in oos_pfs]}))
    return p


def test_subperiod_stability_clean_series(tmp_path):
    vp = _write_verdict(tmp_path, [1.5, 0.8, 1.2, 2.0])
    pf, stab, info = sfs.subperiod_stability(vp)
    assert pf == [1.5, 0.8, 1.2, 2.0]
    assert info["n"] == 4
    assert info["wins"] == 3  # 1.5, 1.2, 2.0 are > 1.0
    assert info["p_edge"] == 0.75
    assert isinstance(stab, float)
    assert 0.0 <= stab <= 100.0


def test_subperiod_stability_none_drops_from_series_but_counts_in_denominator(tmp_path):
    # None is excluded from the stability/wins computation but still counts toward n.
    vp = _write_verdict(tmp_path, [1.5, None, 0.9])
    pf, stab, info = sfs.subperiod_stability(vp)
    assert pf == [1.5, None, 0.9]
    assert info["n"] == 3
    assert info["wins"] == 1  # only 1.5 > 1.0 among the numeric values
    assert info["p_edge"] == 0.333  # round(1/3, 3)
    assert isinstance(stab, float)


def test_subperiod_stability_empty_windows_is_safe(tmp_path):
    vp = _write_verdict(tmp_path, [])
    pf, stab, info = sfs.subperiod_stability(vp)
    assert pf == []
    assert info["n"] == 0
    assert info["wins"] == 0
    assert info["p_edge"] == 0.0  # round(0 / max(1, 0), 3)
    assert isinstance(stab, float)
