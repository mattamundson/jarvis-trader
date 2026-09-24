"""Golden test for iterate.py trade-level sidecar serialization.

Run: engine/.venv/Scripts/python engine/backtest/tests_iterate_trade_capture.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from iterate import _serialize_trade_for_iterate  # noqa: E402


class DummyTrade:
    def to_dict(self) -> dict:
        return {
            "entry_date": "2026-01-02T09:30:00",
            "exit_date": "2026-01-02T10:30:00",
            "direction": "long",
            "entry_price": 5000.25,
            "exit_price": 5004.25,
            "contracts": 2,
            "pnl": 40.0,
            "pnl_pct": 0.004,
            "exit_reason": "target_1",
            "holding_bars": 1,
            "regime": "MidVol",
            "bias": "BULLISH",
        }


def test_serialize_trade_for_iterate() -> None:
    row = {
        "symbol": "MES",
        "strategy": "trend",
        "fast": 60,
        "slow": 200,
        "atr_trail_mult": 2.0,
        "vix_min": 0.0,
        "vix_max": 999.0,
        "vix_regime_block": None,
        "fixed_contracts": 1,
    }
    out = _serialize_trade_for_iterate(DummyTrade(), row)
    expected_keys = {
        "symbol",
        "strategy",
        "fast",
        "slow",
        "atr_trail_mult",
        "vix_min",
        "vix_max",
        "vix_regime_block",
        "fixed_contracts",
        "entry_date",
        "exit_date",
        "direction",
        "entry_price",
        "exit_price",
        "contracts",
        "pnl",
        "pnl_pct",
        "exit_reason",
        "holding_bars",
        "regime",
        "bias",
    }
    assert set(out) == expected_keys, out
    assert out["symbol"] == "MES"
    assert out["fast"] == 60
    assert out["pnl"] == 40.0
    assert out["exit_reason"] == "target_1"
    print("PASS iterate trade serialization preserves combo context + trade pnl fields")


if __name__ == "__main__":
    test_serialize_trade_for_iterate()
