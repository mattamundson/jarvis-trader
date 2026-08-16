"""Contiguous cost-sweep survival regression tests.

The gate-v2 ALT metric `cost_survives_through` must be the most expensive cost
tier such that THAT tier AND every cheaper tier all pass — contiguous from the
cheapest tier. Per-tier PF is non-monotone (slippage shifts entry fills, which
moves stops/targets and changes trade selection), so the prior "highest passing
tier" logic could certify survival through a tier whose cheaper neighbor failed —
overstating cost robustness in certification logic. These tests stub the backtest
with controlled PF sequences and assert the survival summary never jumps a gap.

Both runners share identical survival logic, so each test runs against both.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

RUNNERS = ["backtest.run_mes_trend_rank11", "backtest.run_mgc_trend_rank4"]
CHAMPION = {"fast": 50, "slow": 200, "atr_trail_mult": 2.0}


def _stub_sweep(monkeypatch, mod, pf_by_tier: dict, trades: int = 50):
    """Patch _run_signals_and_backtest to return canned PF/trades per cost tier.

    _run_cost_sweep iterates mod.COST_TIER_ORDER in order, so we hand back PFs in
    that same order regardless of the commission/slippage values passed.
    """
    seq = iter(list(mod.COST_TIER_ORDER))

    def fake(df, fast, slow, atr_trail_mult, commission, slippage_ticks, **kwargs):
        # MGC runners (rewired with --sota in PR #597/#598) call
        # _run_signals_and_backtest(..., sota_hardening=...) — accept and
        # ignore the extra kwarg so the stub works for both runner shapes.
        tier = next(seq)
        return SimpleNamespace(profit_factor=pf_by_tier[tier], total_trades=trades)

    monkeypatch.setattr(mod, "_run_signals_and_backtest", fake)


@pytest.mark.parametrize("modname", RUNNERS)
def test_survival_stops_at_first_gap_despite_later_pass(modname, monkeypatch):
    """optimistic PASS, realistic FAIL, pessimistic PASS (non-monotone), catastrophic FAIL.

    Naive 'highest passing tier' would report 'pessimistic'. Contiguous logic must
    report 'optimistic' — survival breaks at the first failing (realistic) tier.
    """
    mod = importlib.import_module(modname)
    _stub_sweep(
        monkeypatch,
        mod,
        {"optimistic": 1.5, "realistic": 0.8, "pessimistic": 1.3, "catastrophic": 0.5},
    )
    out = mod._run_cost_sweep(df=None, champion_params=CHAMPION)
    assert out["cost_survives_through"] == "optimistic"
    # The later non-contiguous pass is still recorded in the full table.
    assert out["tier_results"]["pessimistic"]["passes"] is True


@pytest.mark.parametrize("modname", RUNNERS)
def test_all_tiers_pass_survives_through_catastrophic(modname, monkeypatch):
    mod = importlib.import_module(modname)
    _stub_sweep(
        monkeypatch,
        mod,
        {"optimistic": 2.0, "realistic": 1.8, "pessimistic": 1.5, "catastrophic": 1.2},
    )
    out = mod._run_cost_sweep(df=None, champion_params=CHAMPION)
    assert out["cost_survives_through"] == "catastrophic"


@pytest.mark.parametrize("modname", RUNNERS)
def test_cheapest_tier_fails_survives_none(modname, monkeypatch):
    mod = importlib.import_module(modname)
    _stub_sweep(
        monkeypatch,
        mod,
        {"optimistic": 0.9, "realistic": 1.5, "pessimistic": 1.5, "catastrophic": 1.5},
    )
    out = mod._run_cost_sweep(df=None, champion_params=CHAMPION)
    assert out["cost_survives_through"] == "none"


@pytest.mark.parametrize("modname", RUNNERS)
def test_contiguous_survival_through_realistic(modname, monkeypatch):
    """optimistic+realistic pass, pessimistic fails → survives through realistic (the ALT floor)."""
    mod = importlib.import_module(modname)
    _stub_sweep(
        monkeypatch,
        mod,
        {"optimistic": 1.6, "realistic": 1.2, "pessimistic": 0.7, "catastrophic": 1.1},
    )
    out = mod._run_cost_sweep(df=None, champion_params=CHAMPION)
    assert out["cost_survives_through"] == "realistic"


@pytest.mark.parametrize("modname", RUNNERS)
def test_low_trade_count_fails_tier(modname, monkeypatch):
    """A tier with PF>1 but too few trades does not count as surviving."""
    mod = importlib.import_module(modname)
    _stub_sweep(
        monkeypatch,
        mod,
        {"optimistic": 1.5, "realistic": 1.5, "pessimistic": 1.5, "catastrophic": 1.5},
        trades=0,
    )
    out = mod._run_cost_sweep(df=None, champion_params=CHAMPION)
    assert out["cost_survives_through"] == "none"
