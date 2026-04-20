"""Regression: CME micro futures contract specs must match published values.

Locks the 2026-04-20 fix where `trader.py:369` tick_value_map was 10× too
high (e.g. MES=$12.50 instead of $1.25). Under-sized Half-Kelly stops,
disabled sizing intelligence. See roadmap Phase 1 Task S1.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Published CME specs: tick_value = dollars-per-point × tick-size
CME_SPECS = {
    "MES": {"dollars_per_point": 5.0,   "tick_size": 0.25, "tick_value": 1.25},
    "MNQ": {"dollars_per_point": 2.0,   "tick_size": 0.25, "tick_value": 0.50},
    "MCL": {"dollars_per_point": 100.0, "tick_size": 0.01, "tick_value": 1.00},
    "MGC": {"dollars_per_point": 10.0,  "tick_size": 0.10, "tick_value": 1.00},
}


@pytest.mark.parametrize("symbol,spec", CME_SPECS.items())
def test_cme_spec_arithmetic_is_self_consistent(symbol, spec):
    computed = spec["dollars_per_point"] * spec["tick_size"]
    assert abs(computed - spec["tick_value"]) < 1e-9, (
        f"{symbol}: spec inconsistency — ${spec['dollars_per_point']}/pt × "
        f"{spec['tick_size']} tick = ${computed} but tick_value declared ${spec['tick_value']}"
    )


@pytest.mark.parametrize("symbol,spec", CME_SPECS.items())
def test_trader_tick_value_map_matches_cme(symbol, spec):
    """The tick_value_map inside trader.py's position-sizing branch must equal CME spec."""
    from agents import trader as trader_mod

    import inspect

    source = inspect.getsource(trader_mod)
    # Look for the literal dict we care about; this is an explicit source-level
    # invariant. If the structure ever changes, this test should be rewritten
    # to import the map directly rather than silently pass.
    assert "tick_value_map" in source, "trader.py no longer defines tick_value_map — update this test"

    # Evaluate the declared literal safely by scanning for the single dict line.
    # Matches the exact form used at trader.py:369 after the 2026-04-20 fix.
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("tick_value_map = {") and "MES" in stripped:
            # Safe because the string is code we authored, not user input.
            declared = eval(stripped.split("=", 1)[1])  # noqa: S307
            assert declared[symbol] == spec["tick_value"], (
                f"{symbol}: trader.py declares tick_value={declared[symbol]} "
                f"but CME spec says {spec['tick_value']} "
                f"(${spec['dollars_per_point']}/pt × {spec['tick_size']} tick)"
            )
            return

    pytest.fail("Could not locate the tick_value_map literal in trader.py")


@pytest.mark.parametrize("symbol,spec", CME_SPECS.items())
def test_orb_backtester_contract_specs_match_cme(symbol, spec):
    if symbol == "MGC":
        pytest.skip("MGC not in orb_backtester CONTRACT_SPECS")
    from backtest.orb_backtester import CONTRACT_SPECS

    assert symbol in CONTRACT_SPECS, f"{symbol} missing from CONTRACT_SPECS"
    declared = CONTRACT_SPECS[symbol]
    assert declared["tick_value"] == spec["tick_value"], (
        f"{symbol}: orb_backtester tick_value={declared['tick_value']} "
        f"but CME spec says {spec['tick_value']}"
    )
    assert declared["multiplier"] == spec["dollars_per_point"], (
        f"{symbol}: orb_backtester multiplier={declared['multiplier']} "
        f"but CME spec says {spec['dollars_per_point']}"
    )
    assert declared["tick_size"] == spec["tick_size"], (
        f"{symbol}: orb_backtester tick_size={declared['tick_size']} "
        f"but CME spec says {spec['tick_size']}"
    )


@pytest.mark.parametrize("symbol,spec", CME_SPECS.items())
def test_position_sizing_instrument_multipliers_match_cme(symbol, spec):
    from utils.position_sizing import INSTRUMENT_MULTIPLIERS

    assert symbol in INSTRUMENT_MULTIPLIERS, f"{symbol} missing from INSTRUMENT_MULTIPLIERS"
    assert INSTRUMENT_MULTIPLIERS[symbol] == spec["dollars_per_point"], (
        f"{symbol}: position_sizing multiplier={INSTRUMENT_MULTIPLIERS[symbol]} "
        f"but CME spec says {spec['dollars_per_point']}"
    )
