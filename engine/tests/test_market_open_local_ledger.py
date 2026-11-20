"""market_open_1h local paper ledger — no IBKR, no ALLOW_PAPER_SIMULATED_ORDERS."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from paper.local_ledger import maybe_log_local_paper_fill


def _result(
    *,
    action: str = "sell",
    entry: float | None = 7646.5,
    stop: float | None = 7660.0,
    qty: int = 2,
) -> dict:
    td: dict = {"confidence": 0.4, "quantity": qty}
    if entry is not None:
        td["entry_price"] = entry
    if stop is not None:
        td["stop_price"] = stop
        td["target_1"] = (entry or 0) - 20.0 if action == "sell" else (entry or 0) + 20.0
    return {
        "final_action": action,
        "final_quantity": qty,
        "confidence": 0.4,
        "summary": f"MES | action={action.upper()} qty={qty} | conviction=0%",
        "trade_decision": td,
        "analyst_reports": {"technical": {"regime": "trending", "trend": "ranging"}},
        "fund_decision": {"final_conviction": 0.0},
    }


def _tracker() -> MagicMock:
    t = MagicMock()
    t.add_paper_trade = MagicMock(return_value="tid-local-1")
    t.get_open_positions = MagicMock(return_value=[])
    return t


def test_hold_does_not_write():
    tracker = _tracker()
    out = maybe_log_local_paper_fill(
        symbol="MES", result=_result(action="hold"), paper_tracker=tracker
    )
    assert out["executed"] is False
    assert out["reason"] == "not_directional"
    tracker.add_paper_trade.assert_not_called()


def test_sell_with_stop_writes_local_row():
    tracker = _tracker()
    out = maybe_log_local_paper_fill(
        symbol="MES", result=_result(action="sell"), paper_tracker=tracker
    )
    assert out["executed"] is True
    assert out["reason"] == "local_ledger"
    tracker.add_paper_trade.assert_called_once()
    kwargs = tracker.add_paper_trade.call_args.kwargs
    assert kwargs["symbol"] == "MES"
    assert kwargs["side"] == "sell"
    assert kwargs["quantity"] == 2.0
    assert kwargs["entry_price"] == 7646.5
    assert kwargs["stop_loss"] == 7660.0
    assert kwargs["strategy_params"]["source"] == "market_open_1h"


def test_missing_stop_blocks():
    tracker = _tracker()
    out = maybe_log_local_paper_fill(
        symbol="MES", result=_result(stop=None), paper_tracker=tracker
    )
    assert out["executed"] is False
    assert out["reason"] == "missing_stop"
    tracker.add_paper_trade.assert_not_called()


def test_missing_entry_blocks():
    tracker = _tracker()
    out = maybe_log_local_paper_fill(
        symbol="MES", result=_result(entry=None), paper_tracker=tracker
    )
    assert out["executed"] is False
    assert out["reason"] == "missing_entry_price"
    tracker.add_paper_trade.assert_not_called()


def test_halted_symbol_blocks(monkeypatch):
    import paper.local_ledger as mod

    monkeypatch.setattr(mod, "_halted", lambda symbol: True)
    tracker = _tracker()
    out = maybe_log_local_paper_fill(
        symbol="MCL", result=_result(), paper_tracker=tracker
    )
    assert out["reason"] == "symbol_halted"
    tracker.add_paper_trade.assert_not_called()


def test_kill_switch_blocks():
    tracker = _tracker()
    safety = MagicMock()
    safety.get_status = MagicMock(return_value={"kill_switch_active": True})
    out = maybe_log_local_paper_fill(
        symbol="MES",
        result=_result(),
        paper_tracker=tracker,
        safety_layer=safety,
    )
    assert out["reason"] == "kill_switch_active"
    tracker.add_paper_trade.assert_not_called()


def test_live_trading_flag_blocks_without_writing():
    tracker = _tracker()
    out = maybe_log_local_paper_fill(
        symbol="MES",
        result=_result(),
        paper_tracker=tracker,
        live_trading_enabled=True,
    )
    assert out["reason"] == "live_trading_enabled"
    tracker.add_paper_trade.assert_not_called()


def test_open_position_dedupes():
    tracker = _tracker()
    tracker.get_open_positions = MagicMock(
        return_value=[{"symbol": "MES", "side": "buy", "trade_id": "open-1"}]
    )
    out = maybe_log_local_paper_fill(
        symbol="MES", result=_result(action="buy"), paper_tracker=tracker
    )
    assert out["reason"] == "paper_position_already_open"
    tracker.add_paper_trade.assert_not_called()


def test_missing_tracker_does_not_raise():
    out = maybe_log_local_paper_fill(
        symbol="MES", result=_result(), paper_tracker=None
    )
    assert out["reason"] == "paper_tracker_missing"


def test_helper_never_calls_broker_gates():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(maybe_log_local_paper_fill.__code__.co_filename).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    assert "ALLOW_PAPER_SIMULATED_ORDERS" not in names
    assert "check_order" not in names
    assert "submit_entry_with_stop" not in names
