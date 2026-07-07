"""Tests for the dealer-GEX options-flow helper (pure, no network)."""

import pytest

from analytics.options_flow import compute_gex


def _contract(ctype: str, strike: float, gamma: float, oi: float) -> dict:
    return {
        "details": {"contract_type": ctype, "strike_price": strike},
        "greeks": {"gamma": gamma},
        "open_interest": oi,
    }


def test_formula_matches_hand_computation():
    spot = 100.0
    # One call: GEX = +1 * gamma * oi * 100 * spot^2 * 0.01
    contracts = [_contract("call", 100, 0.05, 1000)]
    flow = compute_gex(contracts, spot)
    expected = 0.05 * 1000 * 100 * (spot * spot) * 0.01  # = 5_000_000
    assert flow is not None
    assert flow["net_gex"] == pytest.approx(expected)


def test_call_heavy_is_bullish_positive():
    contracts = [
        _contract("call", 100, 0.06, 2000),
        _contract("put", 95, 0.02, 200),
    ]
    flow = compute_gex(contracts, 100.0)
    assert flow is not None
    assert flow["net_gex"] > 0
    assert flow["flow_signal"] == "BULLISH"


def test_put_heavy_is_bearish_negative():
    contracts = [
        _contract("put", 100, 0.06, 2000),
        _contract("call", 105, 0.02, 200),
    ]
    flow = compute_gex(contracts, 100.0)
    assert flow is not None
    assert flow["net_gex"] < 0
    assert flow["flow_signal"] == "BEARISH"


def test_balanced_chain_is_neutral():
    contracts = [
        _contract("call", 100, 0.05, 1000),
        _contract("put", 100, 0.05, 1000),
    ]
    flow = compute_gex(contracts, 100.0)
    assert flow is not None
    assert flow["flow_signal"] == "NEUTRAL"


def test_flip_level_brackets_zero_crossing():
    # Negative gamma at low strikes, positive at high strikes -> flip in between.
    contracts = [
        _contract("put", 90, 0.05, 1000),  # negative GEX
        _contract("call", 110, 0.05, 1000),  # positive GEX
    ]
    flow = compute_gex(contracts, 100.0)
    assert flow is not None
    assert 90 <= flow["gex_flip_level"] <= 110


def test_empty_or_malformed_returns_none():
    assert compute_gex([], 100.0) is None
    assert compute_gex([{"details": {}, "greeks": {}}], 100.0) is None
    # Missing open_interest -> contract skipped -> no usable contracts -> None.
    assert compute_gex([_contract("call", 100, 0.05, 1000)], 0.0) is None


def test_missing_gamma_contract_skipped_not_raised():
    contracts = [
        {"details": {"contract_type": "call", "strike_price": 100}, "greeks": {}, "open_interest": 100},
        _contract("call", 100, 0.05, 1000),
    ]
    flow = compute_gex(contracts, 100.0)
    assert flow is not None  # the one good contract still computes
