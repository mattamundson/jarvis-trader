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
    import inspect

    from agents import trader as trader_mod

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


# ─────────────────────────────────────────────────────────────────────────
# Canonical CONTRACT_SPECS module (2026-04-21). Consolidates duplicate
# per-symbol dicts that had drifted across research scripts — notably MCL
# commission was 0.62 in mes_trend_search.py and 0.85 in mcl_meanrev_search.py.
# The canonical value is 0.85 (IB tier 1 NYMEX micro actual).
# ─────────────────────────────────────────────────────────────────────────

class TestCanonicalContractSpecs:
    def test_mes_canonical_values(self):
        from backtest.contract_specs import get_spec
        spec = get_spec("MES")
        assert spec.multiplier == 5.0
        assert spec.tick_size == 0.25
        assert spec.commission == 0.71
        assert spec.slippage_ticks == 1
        assert spec.tick_value == 1.25

    def test_mcl_commission_canonical_is_85_cents(self):
        """MCL commission was the drift (0.62 in one script, 0.85 in others).
        Canonical is 0.85 — IB tier 1 NYMEX micro actual round-trip rate."""
        from backtest.contract_specs import get_spec
        spec = get_spec("MCL")
        assert spec.multiplier == 100.0
        assert spec.tick_size == 0.01
        assert spec.commission == 0.85
        assert spec.tick_value == 1.0

    def test_mnq_slippage_is_2_ticks(self):
        """MNQ gaps through stops more than MES — 2 ticks, not 1.
        Empirical from live paper logs; update only with new evidence."""
        from backtest.contract_specs import get_spec
        spec = get_spec("MNQ")
        assert spec.slippage_ticks == 2, (
            "MNQ slippage is 2 ticks, not 1. Update contract_specs.py with "
            "evidence in the commit message if this changes."
        )

    def test_round_trip_commission_helper(self):
        from backtest.contract_specs import get_spec
        spec = get_spec("MES")
        assert spec.round_trip_commission == 1.42  # 2 × 0.71

    def test_get_spec_case_insensitive(self):
        from backtest.contract_specs import get_spec
        assert get_spec("mes") is get_spec("MES")

    def test_unknown_symbol_raises_helpful_error(self):
        from backtest.contract_specs import get_spec
        with pytest.raises(KeyError, match="No contract spec"):
            get_spec("ZZZZ_UNKNOWN")

    def test_backward_compat_multipliers_view(self):
        """Legacy CONTRACT_MULTIPLIERS view must track spec multipliers."""
        from backtest.contract_specs import CONTRACT_MULTIPLIERS, CONTRACT_SPECS
        for sym, spec in CONTRACT_SPECS.items():
            assert CONTRACT_MULTIPLIERS[sym] == spec.multiplier

    def test_specs_are_immutable(self):
        """Frozen dataclass prevents accidental mutation during backtests."""
        from dataclasses import FrozenInstanceError

        from backtest.contract_specs import get_spec
        spec = get_spec("MES")
        with pytest.raises(FrozenInstanceError):
            spec.multiplier = 999.0  # type: ignore[misc]

    def test_required_live_symbols_present(self):
        """These symbols are actively traded or in paper validation."""
        from backtest.contract_specs import CONTRACT_SPECS
        required = {"MES", "MCL", "MNQ", "MGC", "SPY"}
        missing = required - set(CONTRACT_SPECS.keys())
        assert not missing, f"Missing canonical specs: {missing}"

    @pytest.mark.parametrize("symbol", ["MES", "MNQ", "MCL", "MGC"])
    def test_canonical_matches_cme_arithmetic(self, symbol):
        """Canonical CONTRACT_SPECS tick_value must match CME_SPECS (source of truth)."""
        from backtest.contract_specs import get_spec
        canonical = get_spec(symbol)
        cme = CME_SPECS[symbol]
        assert canonical.tick_value == cme["tick_value"], (
            f"{symbol}: canonical tick_value={canonical.tick_value} "
            f"but CME spec says {cme['tick_value']}"
        )
