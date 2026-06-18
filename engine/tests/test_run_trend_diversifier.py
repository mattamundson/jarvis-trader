"""Tests for the generic B1 trend-diversifier runner (backtest/run_trend_diversifier.py).

These exercise the symbol-parameterization, the new rates/FX contract specs, the
cost-tier ladder, and the staged "awaiting data pull" path -- without running a
full WFO backtest (no cache data is required).
"""

from __future__ import annotations

import pytest

from backtest import contract_specs
from backtest import run_trend_diversifier as rd

# --- new B1 contract specs --------------------------------------------------


@pytest.mark.parametrize(
    "symbol, mult, tick, tick_value",
    [
        ("ZN", 1000.0, 0.015625, 15.625),
        ("ZB", 1000.0, 0.03125, 31.25),
        ("M6E", 12500.0, 0.0001, 1.25),
        ("M6B", 6250.0, 0.0001, 0.625),
    ],
)
def test_b1_specs_registered_with_correct_tick_value(symbol, mult, tick, tick_value):
    spec = contract_specs.get_spec(symbol)
    assert spec.multiplier == mult
    assert spec.tick_size == tick
    assert spec.tick_value == pytest.approx(tick_value)


def test_staged_diversifier_set_all_have_specs():
    # Every staged B1 candidate must resolve a spec so the runner can build a config.
    for sym in rd.STAGED_DIVERSIFIERS:
        cfg = rd.config_for(sym)
        assert cfg.symbol == sym
        assert cfg.multiplier > 0
        assert cfg.tick_size > 0


def test_staged_diversifiers_are_pullable_via_ibkr_export():
    # The IB history puller must know each staged symbol's contract (exchange/
    # currency) or a pull fails on contract identification. This keeps the puller
    # and the runner's staged set in lock-step.
    from backtest.export_ibkr_history import SYMBOL_TO_IB_SPEC

    for sym in rd.STAGED_DIVERSIFIERS:
        assert sym in SYMBOL_TO_IB_SPEC, f"{sym} missing from export_ibkr_history.SYMBOL_TO_IB_SPEC"
        spec = SYMBOL_TO_IB_SPEC[sym]
        assert spec["symbol"] == sym
        assert spec["exchange"]  # non-empty exchange required for IB resolution
        assert spec["currency"] == "USD"


# --- config_for -------------------------------------------------------------


def test_config_for_pulls_from_contract_specs():
    cfg = rd.config_for("ZN", capital=25_000.0)
    spec = contract_specs.get_spec("ZN")
    assert cfg.multiplier == spec.multiplier
    assert cfg.commission == spec.commission
    assert cfg.slippage_ticks == float(spec.slippage_ticks)
    assert cfg.capital == 25_000.0


def test_config_for_unknown_symbol_raises():
    with pytest.raises(KeyError):
        rd.config_for("NOTASYMBOL")


def test_default_grid_is_eight_combos():
    cfg = rd.config_for("ZN")
    assert len(cfg.grid) == 8  # 2 fast x 2 slow x 2 atr-trail


# --- cost-tier ladder -------------------------------------------------------


def test_cost_tiers_scale_from_base():
    tiers = rd.cost_tiers(commission=1.20, slippage_ticks=1.0)
    assert tiers["optimistic"]["commission"] == pytest.approx(0.60)
    assert tiers["realistic"]["commission"] == pytest.approx(1.20)
    assert tiers["pessimistic"]["commission"] == pytest.approx(2.40)
    assert tiers["catastrophic"]["commission"] == pytest.approx(4.80)
    # slippage: base held for optimistic/realistic, +1 / +2 for the worse tiers.
    assert tiers["optimistic"]["slippage_ticks"] == 1.0
    assert tiers["realistic"]["slippage_ticks"] == 1.0
    assert tiers["pessimistic"]["slippage_ticks"] == 2.0
    assert tiers["catastrophic"]["slippage_ticks"] == 3.0


# --- staged "awaiting data" path (no cache required) ------------------------


def test_find_data_file_absent_returns_none(tmp_path):
    # A symbol with no cache anywhere resolves to None (staged), not an exception.
    assert rd.find_data_file("ZZZNODATA", data_dir=tmp_path) is None


def test_run_wfo_awaiting_data_returns_empty(capsys):
    # Construct a config for a guaranteed-absent symbol directly (bypass the spec
    # lookup) so the test is hermetic and never triggers a real backtest.
    cfg = rd.RunConfig(
        symbol="ZZZNODATA",
        multiplier=1000.0,
        tick_size=0.01,
        commission=1.0,
        slippage_ticks=1.0,
        capital=50_000.0,
    )
    result = rd.run_wfo(cfg)
    assert result == {}
    out = capsys.readouterr().out
    assert "AWAITING DATA PULL" in out
