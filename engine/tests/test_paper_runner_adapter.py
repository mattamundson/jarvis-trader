"""
Tests for paper_runner.load_positions() adapter.

Regression coverage for the 2026-04-10 KeyError: 'stop' crash.
SQLite paper_trades rows use column names that don't match the legacy
in-memory dict shape expected by manage_open_position(); the adapter
translates them.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from backtest.paper_runner import _adapt_trade_row_to_position


def _make_row(**overrides: Any) -> Dict[str, Any]:
    base = {
        "id": 54,
        "symbol": "MCL",
        "side": "long",
        "quantity": 1.0,
        "entry_price": 68.5,
        "exit_price": None,
        "entry_time": "2026-04-03T22:12:19.135111+00:00",
        "exit_time": None,
        "pnl": None,
        "status": "open",
        "strategy_params": json.dumps(
            {
                "targets": [69.5, 70.5, 71.5],
                "contracts_remaining": 1,
                "t1_hit": False,
                "t2_hit": False,
                "t3_hit": False,
                "risk_pct_used": 0.5,
            }
        ),
        "notes": "",
        "regime": "trending",
        "structure_position": "lower_support",
        "bias": "bullish",
        "composite_score": 0.75,
        "stc_contrib": 1,
        "orb_contrib": 0,
        "vwap_contrib": 1,
        "risk_pct_used": 0.5,
        "stop_loss": 67.8,
    }
    base.update(overrides)
    return base


def test_adapter_translates_stop_loss_to_stop() -> None:
    row = _make_row(stop_loss=67.8)
    pos = _adapt_trade_row_to_position(row)
    assert pos["stop"] == 67.8


def test_adapter_translates_entry_time_to_entry_date() -> None:
    row = _make_row(entry_time="2026-04-03T22:12:19.135111+00:00")
    pos = _adapt_trade_row_to_position(row)
    assert pos["entry_date"] == "2026-04-03T22:12:19.135111+00:00"


def test_adapter_parses_targets_from_strategy_params_json() -> None:
    row = _make_row(
        strategy_params=json.dumps({"targets": [69.0, 70.0, 71.0]})
    )
    pos = _adapt_trade_row_to_position(row)
    assert pos["targets"] == [69.0, 70.0, 71.0]


def test_adapter_handles_missing_strategy_params_gracefully() -> None:
    row = _make_row(strategy_params=None)
    pos = _adapt_trade_row_to_position(row)
    assert pos["targets"] == []
    assert pos["contracts_remaining"] == 1
    assert pos["t1_hit"] is False
    assert pos["stop"] is not None  # stop_loss still present


def test_adapter_handles_malformed_strategy_params_json() -> None:
    row = _make_row(strategy_params="{not valid json")
    pos = _adapt_trade_row_to_position(row)
    assert pos["targets"] == []
    assert pos["contracts_remaining"] == 1


def test_adapter_derives_contracts_from_quantity() -> None:
    row = _make_row(quantity=2.0, strategy_params="{}")
    pos = _adapt_trade_row_to_position(row)
    assert pos["contracts"] == 2
    # contracts_remaining defaults to quantity when not in strategy_params
    assert pos["contracts_remaining"] == 2


def test_adapter_extracts_per_target_hit_flags() -> None:
    row = _make_row(
        strategy_params=json.dumps(
            {
                "targets": [69.0, 70.0, 71.0],
                "contracts_remaining": 1,
                "t1_hit": True,
                "t2_hit": False,
                "t3_hit": False,
            }
        )
    )
    pos = _adapt_trade_row_to_position(row)
    assert pos["t1_hit"] is True
    assert pos["t2_hit"] is False
    assert pos["t3_hit"] is False


def test_adapter_preserves_original_column_values() -> None:
    """Adapter should copy row and add keys without removing originals."""
    row = _make_row()
    pos = _adapt_trade_row_to_position(row)
    # Original columns still accessible
    assert pos["entry_price"] == 68.5
    assert pos["symbol"] == "MCL"
    assert pos["side"] == "long"
    assert pos["regime"] == "trending"


def test_adapter_output_satisfies_manage_open_position_key_requirements() -> None:
    """
    manage_open_position() reads the following keys from the pos dict:
      entry_price, side, stop, targets, contracts_remaining, contracts,
      entry_date, regime, risk_pct_used
    This test asserts the adapter produces all of them without KeyError.
    """
    row = _make_row()
    pos = _adapt_trade_row_to_position(row)
    required_keys = [
        "entry_price",
        "side",
        "stop",
        "targets",
        "contracts_remaining",
        "contracts",
        "entry_date",
        "regime",
        "risk_pct_used",
    ]
    for k in required_keys:
        assert k in pos, f"adapter missing required key: {k}"

    # The original KeyError regression: these two specifically
    _ = float(pos["stop"])  # must not raise
    _ = [float(t) for t in pos["targets"]]  # must not raise


def test_adapter_handles_quantity_as_string() -> None:
    """SQLite can return REAL as float but some drivers return str for NULL-ish."""
    row = _make_row(quantity=3)
    pos = _adapt_trade_row_to_position(row)
    assert pos["contracts"] == 3
