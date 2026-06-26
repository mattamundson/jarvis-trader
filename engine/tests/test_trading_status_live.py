"""Tests for services.trading_status_live — the per-symbol runtime-state half of
the /trading-status surface. Pure logic; no DB, no engine, no broker.
"""

from __future__ import annotations

from datetime import datetime, timezone

from services.trading_status_live import (
    SymbolLiveState,
    build_live_status,
    build_symbol_live_state,
    summarize_live,
)

# A fixed clock so age math is deterministic.
NOW = datetime(2026, 6, 22, 16, 0, 0, tzinfo=timezone.utc)


def _signal(ts="2026-06-22T15:59:30+00:00", action="buy", confidence=0.82, regime="trend"):
    # Includes extra columns the normalizer must ignore.
    return {
        "id": 7,
        "symbol": "MES",
        "timestamp": ts,
        "action": action,
        "confidence": confidence,
        "regime": regime,
        "signal_data_json": "{...}",
        "full_pipeline_json": "{...}",
    }


def _order(status="closed", side="buy", pnl=12.5):
    return {
        "id": 3,
        "trade_id": "T-100",
        "symbol": "MES",
        "side": side,
        "quantity": 1.0,
        "entry_price": 5300.0,
        "exit_price": 5312.5,
        "entry_time": "2026-06-22T15:40:00+00:00",
        "exit_time": "2026-06-22T15:58:00+00:00",
        "pnl": pnl,
        "status": status,
        "strategy_params": "{...}",
    }


def _open_position(side="buy"):
    return {
        "trade_id": "T-101",
        "symbol": "MES",
        "side": side,
        "quantity": 2.0,
        "entry_price": 5310.0,
        "entry_time": "2026-06-22T15:55:00+00:00",
        "status": "open",
    }


# ---------------------------------------------------------------- single symbol


def test_full_state_assembles_all_four_sources():
    s = build_symbol_live_state(
        "MES",
        last_signal_row=_signal(),
        last_order_row=_order(),
        open_position_row=_open_position(),
        realized_pnl=42.0,
        now=NOW,
    )
    assert s.symbol == "MES"
    assert s.last_signal["action"] == "buy"
    assert s.last_signal["confidence"] == 0.82
    assert s.last_signal["regime"] == "trend"
    assert s.last_signal["age_seconds"] == 30.0  # 16:00:00 - 15:59:30
    assert s.last_order["trade_id"] == "T-100"
    assert s.last_order["status"] == "closed"
    assert s.last_order["pnl"] == 12.5
    assert s.open_position["trade_id"] == "T-101"
    assert s.open_position["quantity"] == 2.0
    assert s.has_open_position is True
    assert s.realized_pnl == 42.0


def test_no_data_yields_all_none_and_no_position():
    s = build_symbol_live_state(
        "MGC",
        last_signal_row=None,
        last_order_row=None,
        open_position_row=None,
        realized_pnl=None,
        now=NOW,
    )
    assert s.last_signal is None
    assert s.last_order is None
    assert s.open_position is None
    assert s.has_open_position is False
    assert s.realized_pnl is None


def test_has_open_position_derives_from_position_presence():
    with_pos = build_symbol_live_state(
        "MES",
        last_signal_row=None,
        last_order_row=None,
        open_position_row=_open_position(),
        realized_pnl=None,
        now=NOW,
    )
    without_pos = build_symbol_live_state(
        "MES",
        last_signal_row=None,
        last_order_row=None,
        open_position_row=None,
        realized_pnl=None,
        now=NOW,
    )
    assert with_pos.has_open_position is True
    assert without_pos.has_open_position is False


def test_signal_normalizer_projects_only_exposed_fields():
    s = build_symbol_live_state(
        "MES",
        last_signal_row=_signal(),
        last_order_row=None,
        open_position_row=None,
        realized_pnl=None,
        now=NOW,
    )
    assert set(s.last_signal.keys()) == {
        "action",
        "confidence",
        "regime",
        "timestamp",
        "age_seconds",
    }
    # raw DB columns must not leak through
    assert "signal_data_json" not in s.last_signal
    assert "full_pipeline_json" not in s.last_signal
    assert "id" not in s.last_signal


def test_order_normalizer_projects_only_exposed_fields():
    s = build_symbol_live_state(
        "MES",
        last_signal_row=None,
        last_order_row=_order(),
        open_position_row=None,
        realized_pnl=None,
        now=NOW,
    )
    assert set(s.last_order.keys()) == {
        "trade_id",
        "side",
        "quantity",
        "entry_price",
        "exit_price",
        "status",
        "entry_time",
        "exit_time",
        "pnl",
    }
    assert "strategy_params" not in s.last_order


def test_position_side_falls_back_to_action_column():
    # open-trade store wrote direction under 'action', not 'side'
    row = {
        "trade_id": "T-9",
        "action": "sell",
        "quantity": 1.0,
        "entry_price": 100.0,
        "entry_time": "2026-06-22T15:00:00+00:00",
    }
    s = build_symbol_live_state(
        "MES",
        last_signal_row=None,
        last_order_row=None,
        open_position_row=row,
        realized_pnl=None,
        now=NOW,
    )
    assert s.open_position["side"] == "sell"


def test_age_seconds_none_when_timestamp_unparseable():
    s = build_symbol_live_state(
        "MES",
        last_signal_row=_signal(ts="not-a-date"),
        last_order_row=None,
        open_position_row=None,
        realized_pnl=None,
        now=NOW,
    )
    assert s.last_signal["age_seconds"] is None


def test_age_seconds_handles_z_suffix_and_naive_timestamps():
    z = build_symbol_live_state(
        "MES",
        last_signal_row=_signal(ts="2026-06-22T15:59:00Z"),
        last_order_row=None,
        open_position_row=None,
        realized_pnl=None,
        now=NOW,
    )
    naive = build_symbol_live_state(
        "MES",
        last_signal_row=_signal(ts="2026-06-22T15:59:00"),
        last_order_row=None,
        open_position_row=None,
        realized_pnl=None,
        now=NOW,
    )
    assert z.last_signal["age_seconds"] == 60.0
    assert naive.last_signal["age_seconds"] == 60.0


def test_age_seconds_none_without_clock():
    s = build_symbol_live_state(
        "MES",
        last_signal_row=_signal(),
        last_order_row=None,
        open_position_row=None,
        realized_pnl=None,
        now=None,
    )
    assert s.last_signal["age_seconds"] is None


def test_missing_keys_in_rows_do_not_raise():
    s = build_symbol_live_state(
        "MES",
        last_signal_row={},  # empty dicts are falsy -> normalize to None
        last_order_row={"trade_id": "X"},  # partial row
        open_position_row={"quantity": 3},  # no side/action
        realized_pnl=None,
        now=NOW,
    )
    assert s.last_signal is None  # {} is falsy
    assert s.last_order["trade_id"] == "X"
    assert s.last_order["side"] is None
    assert s.open_position["side"] is None
    assert s.has_open_position is True


# ---------------------------------------------------------------- multi symbol


def test_build_live_status_sorts_and_dedups():
    seen = []

    def sig(sym):
        seen.append(sym)
        return None

    states = build_live_status(
        ["MNQ", "MES", "MES", "MGC"],
        last_signal_for=sig,
        last_order_for=lambda s: None,
        open_position_for=lambda s: None,
        realized_pnl_for=lambda s: None,
        now=NOW,
    )
    assert [s.symbol for s in states] == ["MES", "MGC", "MNQ"]
    # de-duplicated: MES queried once, not twice
    assert sorted(seen) == ["MES", "MGC", "MNQ"]


def test_build_live_status_routes_each_callable_per_symbol():
    states = build_live_status(
        ["MES", "MGC"],
        last_signal_for=lambda s: _signal() if s == "MES" else None,
        last_order_for=lambda s: _order() if s == "MGC" else None,
        open_position_for=lambda s: _open_position() if s == "MES" else None,
        realized_pnl_for=lambda s: 5.0 if s == "MGC" else None,
        now=NOW,
    )
    by = {s.symbol: s for s in states}
    assert by["MES"].last_signal is not None
    assert by["MES"].has_open_position is True
    assert by["MES"].last_order is None
    assert by["MGC"].last_order is not None
    assert by["MGC"].realized_pnl == 5.0
    assert by["MGC"].last_signal is None


# ------------------------------------------------------------------- summarize


def test_summarize_live_counts():
    states = build_live_status(
        ["MES", "MGC", "MNQ"],
        last_signal_for=lambda s: _signal() if s in ("MES", "MNQ") else None,
        last_order_for=lambda s: None,
        open_position_for=lambda s: _open_position() if s == "MES" else None,
        realized_pnl_for=lambda s: {"MES": 10.0, "MGC": -4.0, "MNQ": None}[s],
        now=NOW,
    )
    summary = summarize_live(states)
    assert summary["total"] == 3
    assert summary["with_open_position"] == 1  # MES only
    assert summary["with_signal"] == 2  # MES, MNQ
    assert summary["total_realized_pnl"] == 6.0  # 10 + (-4) + 0(None)


def test_summarize_live_empty():
    summary = summarize_live([])
    assert summary == {
        "total": 0,
        "with_open_position": 0,
        "with_signal": 0,
        "total_realized_pnl": 0.0,
    }


# ----------------------------------------------------------------- json-friendly


def test_to_dict_is_json_friendly():
    import json

    s = build_symbol_live_state(
        "MES",
        last_signal_row=_signal(),
        last_order_row=_order(),
        open_position_row=_open_position(),
        realized_pnl=42.0,
        now=NOW,
    )
    d = s.to_dict()
    # round-trips through json without custom encoders
    assert json.loads(json.dumps(d))["symbol"] == "MES"
    assert isinstance(s, SymbolLiveState)
