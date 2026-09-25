"""Regression: Corey weight elevation for futures symbols (Phase 4 Task D4).

Per the 2026-04-19 owner directive, Corey's #market-updates channel is the
authoritative futures sentiment source. This test locks the D4 elevation:
- Futures symbols (MCL/MNQ/MES/MGC) get a Corey weight floor of 1.20
- Equity-style symbols are untouched
- A historically-accurate Corey above the floor is not regressed downward
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.debate import (  # noqa: E402
    COREY_FUTURES_SYMBOLS,
    COREY_FUTURES_WEIGHT_FLOOR,
    _apply_corey_futures_elevation,
)

# ── Basic contract assertions ────────────────────────────────────────────────


def test_futures_set_contains_expected_symbols():
    assert COREY_FUTURES_SYMBOLS == frozenset({"MCL", "MNQ", "MES", "MGC"})


def test_elevation_floor_is_near_max_weight():
    # AgentFeedbackTracker.MAX_WEIGHT is 1.30 — the floor should be close to
    # that cap so it meaningfully amplifies Corey's signal.
    assert 1.15 <= COREY_FUTURES_WEIGHT_FLOOR <= 1.30


# ── Futures: weight is floored ───────────────────────────────────────────────


@pytest.mark.parametrize("futures_symbol", ["MCL", "MNQ", "MES", "MGC"])
def test_elevation_floors_low_corey_weight_for_futures(futures_symbol):
    weights = {"corey": 0.85, "news": 1.0, "technical": 1.1}
    result = _apply_corey_futures_elevation(weights, futures_symbol)
    assert result["corey"] == COREY_FUTURES_WEIGHT_FLOOR
    # Other weights unchanged
    assert result["news"] == 1.0
    assert result["technical"] == 1.1


@pytest.mark.parametrize("futures_symbol", ["MCL", "MNQ", "MES", "MGC"])
def test_elevation_case_insensitive_for_futures(futures_symbol):
    weights = {"corey": 0.90}
    for variant in [futures_symbol.lower(), futures_symbol.upper(), futures_symbol.capitalize()]:
        result = _apply_corey_futures_elevation(weights, variant)
        assert result["corey"] == COREY_FUTURES_WEIGHT_FLOOR, f"failed on {variant}"


def test_elevation_preserves_above_floor_corey_weight():
    """A historically-accurate Corey above the floor must not be regressed down."""
    weights = {"corey": 1.28}  # near MAX_WEIGHT
    result = _apply_corey_futures_elevation(weights, "MCL")
    assert result["corey"] == 1.28


def test_elevation_missing_corey_key_sets_default_then_floors():
    """If weights dict has no corey entry, default 1.0 is floored to 1.20."""
    weights = {"news": 1.0, "technical": 1.1}
    result = _apply_corey_futures_elevation(weights, "MES")
    assert result["corey"] == COREY_FUTURES_WEIGHT_FLOOR


# ── Equities: untouched ──────────────────────────────────────────────────────


@pytest.mark.parametrize("equity_symbol", ["AAPL", "SPY", "QQQ", "TSLA", "NVDA", "BTC-USD"])
def test_elevation_noop_for_non_futures(equity_symbol):
    weights = {"corey": 0.85, "news": 1.0}
    result = _apply_corey_futures_elevation(weights, equity_symbol)
    assert result["corey"] == 0.85, f"equity symbol {equity_symbol} incorrectly elevated"


# ── Returns a copy, not the original ─────────────────────────────────────────


def test_elevation_does_not_mutate_input_dict_for_futures():
    original = {"corey": 0.85}
    result = _apply_corey_futures_elevation(original, "MCL")
    assert original["corey"] == 0.85  # unchanged
    assert result["corey"] == COREY_FUTURES_WEIGHT_FLOOR


def test_elevation_does_not_mutate_input_dict_for_equities():
    original = {"corey": 0.85}
    result = _apply_corey_futures_elevation(original, "AAPL")
    # For no-op case we may return the same dict — but original should not be mutated
    assert original["corey"] == 0.85


# ── Defensive: malformed symbol types ────────────────────────────────────────


def test_elevation_handles_none_symbol():
    weights = {"corey": 0.85}
    # Should not raise; should leave weights unchanged (no-op).
    result = _apply_corey_futures_elevation(weights, None)  # type: ignore[arg-type]
    assert result["corey"] == 0.85


def test_elevation_handles_non_string_symbol():
    weights = {"corey": 0.85}
    result = _apply_corey_futures_elevation(weights, 123)  # type: ignore[arg-type]
    assert result["corey"] == 0.85


# ── Symmetric with the futures-sentiment-source directive ────────────────────


@pytest.mark.parametrize("symbol", sorted(COREY_FUTURES_SYMBOLS))
def test_all_four_futures_tickers_get_elevation(symbol):
    """Mirror of the social_analyst.py futures-sentiment-source regression test:
    every ticker gated for Corey-only sentiment should also receive the
    Stage-1 elevation here.
    """
    weights = {"corey": 1.0}
    result = _apply_corey_futures_elevation(weights, symbol)
    assert result["corey"] == COREY_FUTURES_WEIGHT_FLOOR
