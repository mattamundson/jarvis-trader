"""Tests for per-window sample-adequacy enforcement (Task 8 follow-on).

The aggregate ``GATE_V2_ENFORCE_SAMPLE_ADEQUACY`` floor is necessary but not
sufficient: a strategy can clear 30 aggregate OOS trades while its median window
is 1-4 trades (e.g. MGC_trend_rank4). ``GATE_V2_ENFORCE_PER_WINDOW`` closes that
gap at the verdict layer. Shadow-default OFF -> no live behavior change until Amo
flips the flag.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backtest import _gate_v2_helpers as gh
from backtest import study_wfo_runner as swr

# ── primitive: the env switch ────────────────────────────────────────────────


def test_per_window_enforce_default_off(monkeypatch):
    monkeypatch.delenv("GATE_V2_ENFORCE_PER_WINDOW", raising=False)
    assert gh.per_window_adequacy_enforced() is False


def test_per_window_enforce_truthy_values(monkeypatch):
    for v in ("1", "true", "TRUE", "yes", "on", "On"):
        monkeypatch.setenv("GATE_V2_ENFORCE_PER_WINDOW", v)
        assert gh.per_window_adequacy_enforced() is True, v
    for v in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("GATE_V2_ENFORCE_PER_WINDOW", v)
        assert gh.per_window_adequacy_enforced() is False, v


# ── primitive: median adequacy ───────────────────────────────────────────────


def test_median_adequate_fat_windows():
    assert gh.per_window_sample_adequate([61, 56, 64, 60, 58, 63, 19]) is True  # median 60


def test_median_inadequate_thin_windows():
    # MGC_trend_rank4 distribution: median 4 < 5.
    rank4 = [5, 5, 7, 5, 3, 4, 4, 4, 4, 3, 2, 4, 5, 3, 2, 1, 1, 3, 2]
    assert gh.per_window_sample_adequate(rank4) is False


def test_median_exactly_at_floor_is_adequate():
    assert gh.per_window_sample_adequate([5, 5, 5]) is True  # median 5 >= 5


def test_empty_per_window_is_failsafe_inadequate():
    assert gh.per_window_sample_adequate([]) is False
    assert gh.per_window_sample_adequate(None) is False


# ── wiring: _compute_gate_v2 honors the flag ─────────────────────────────────


def _mk_results(trades_per_window, pf=1.6, dd=0.02, sharpe=1.2):
    return [
        SimpleNamespace(total_trades=t, profit_factor=pf, max_drawdown_pct=dd, sharpe_ratio=sharpe)
        for t in trades_per_window
    ]


_FIXED = {"fixed_params_min_pf": 1.5, "fixed_params_mean_pf": 1.5, "fixed_params_max_pf": 1.5}
_COST = {"cost_survives_through": "pessimistic", "tier_results": {}}


def test_shadow_off_thin_windows_not_forced_insufficient(monkeypatch):
    # 7 thin windows (4 trades each = 28 aggregate, >= the 20/3 low-power floor).
    monkeypatch.delenv("GATE_V2_ENFORCE_PER_WINDOW", raising=False)
    g = swr._compute_gate_v2(
        _mk_results([4] * 7), n_grid=2, fixed_metrics=_FIXED, cost_metrics=_COST
    )
    # Per-window did not force the verdict; it is recorded but not enforced.
    assert g["median_oos_trades_per_window"] == 4
    assert g["per_window_adequate"] is False
    assert g["verdict"] != "INSUFFICIENT_SAMPLE" or g["total_oos_trades"] < 20


def test_enforce_on_thin_windows_flips_to_insufficient(monkeypatch):
    monkeypatch.setenv("GATE_V2_ENFORCE_PER_WINDOW", "1")
    g = swr._compute_gate_v2(
        _mk_results([4] * 7), n_grid=2, fixed_metrics=_FIXED, cost_metrics=_COST
    )
    assert g["verdict"] == "INSUFFICIENT_SAMPLE"
    assert g["passed_via"] is None
    assert g["per_window_adequate"] is False


def test_enforce_on_fat_windows_not_blocked_by_per_window(monkeypatch):
    monkeypatch.setenv("GATE_V2_ENFORCE_PER_WINDOW", "1")
    g = swr._compute_gate_v2(
        _mk_results([60] * 7), n_grid=2, fixed_metrics=_FIXED, cost_metrics=_COST
    )
    # Fat windows clear the per-window floor -> per-window does not force insufficient.
    assert g["per_window_adequate"] is True
    assert g["median_oos_trades_per_window"] == 60
    assert g["verdict"] != "INSUFFICIENT_SAMPLE"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
