"""
Tests for engine/execution/ledger_fill_sync.py

The paper_trades ledger must reflect what IB actually filled, not the quote
the order was priced from or the theoretical stop level. Fixture shapes come
from cert row 347 (2026-10-27): entry order 5 filled 7707.75 against a
7704.75 quote, OCA children stop=6 / target=7, exit filled at 7708.75.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from execution.ledger_fill_sync import (
    match_fills,
    sync_ledger_from_executions,
)

MES_MULT = 5.0
MES_TICK = 0.25


def _exec(order_id, side, price, qty=1.0, commission=0.62, t="2026-10-27 08:51:32+00:00",
          account="DUR303001", exec_id=None):
    return {
        "exec_id": exec_id or f"x-{order_id}-{price}",
        "account": account,
        "symbol": "MES",
        "side": side,
        "quantity": qty,
        "price": price,
        "avg_price": price,
        "commission": commission,
        "fill_time": t,
        "order_id": order_id,
    }


def _trade(side="buy", entry=7704.75, qty=1.0, status="open"):
    return {
        "trade_id": "e1adfa09",
        "symbol": "MES",
        "side": side,
        "quantity": qty,
        "entry_price": entry,
        "status": status,
        "stop_order_id": "6",
        "target_order_id": "7",
        "strategy_params": json.dumps({"entry_order_id": "5"}),
    }


def test_entry_fill_replaces_quote_and_scores_adverse_slippage():
    m = match_fills(_trade(), [_exec(5, "BOT", 7707.75)], MES_MULT, MES_TICK)
    assert m.entry_fill_price == 7707.75
    # long paid 3.00 points more than the quote = 12 adverse ticks
    assert m.slippage_ticks == pytest.approx(12.0)
    assert m.broker_account == "DUR303001"
    assert m.closed is False


def test_short_slippage_sign_is_adverse_when_filled_lower():
    m = match_fills(_trade(side="sell"), [_exec(5, "SLD", 7704.25)], MES_MULT, MES_TICK)
    assert m.slippage_ticks == pytest.approx(2.0)


def test_exit_fill_closes_with_pnl_net_of_actual_commissions():
    execs = [
        _exec(5, "BOT", 7707.75, commission=0.62),
        _exec(7, "SLD", 7708.75, commission=0.62, t="2026-10-27 08:53:55+00:00"),
    ]
    m = match_fills(_trade(), execs, MES_MULT, MES_TICK)
    assert m.closed is True
    assert m.exit_price == 7708.75
    assert m.exit_time == "2026-10-27 08:53:55+00:00"
    # (7708.75 - 7707.75) * 1 * 5 = 5.00 gross, minus 1.24 broker commission
    assert m.pnl == pytest.approx(3.76)


def test_short_stop_out_pnl_is_negative():
    execs = [
        _exec(5, "SLD", 7700.00, commission=0.62),
        _exec(6, "BOT", 7710.00, commission=0.62),
    ]
    m = match_fills(_trade(side="sell", entry=7700.0), execs, MES_MULT, MES_TICK)
    assert m.closed is True
    assert m.pnl == pytest.approx(-50.0 - 1.24)


def test_partial_entry_fills_use_vwap():
    execs = [
        _exec(5, "BOT", 7700.00, qty=1.0, exec_id="a"),
        _exec(5, "BOT", 7701.00, qty=1.0, exec_id="b"),
    ]
    m = match_fills(_trade(qty=2.0, entry=7700.0), execs, MES_MULT, MES_TICK)
    assert m.entry_fill_price == pytest.approx(7700.50)
    assert m.entry_filled_qty == 2.0


def test_partial_exit_does_not_close():
    execs = [
        _exec(5, "BOT", 7700.00, qty=2.0),
        _exec(6, "SLD", 7690.00, qty=1.0),
    ]
    m = match_fills(_trade(qty=2.0, entry=7700.0), execs, MES_MULT, MES_TICK)
    assert m.closed is False


def test_missing_commission_falls_back_to_none_not_zero():
    """An unknown commission must not silently book a commission-free pnl."""
    execs = [
        _exec(5, "BOT", 7700.00, commission=None),
        _exec(7, "SLD", 7701.00, commission=0.62),
    ]
    m = match_fills(_trade(entry=7700.0), execs, MES_MULT, MES_TICK)
    assert m.closed is True
    assert m.pnl is None


def test_unrelated_executions_are_ignored():
    m = match_fills(_trade(), [_exec(99, "BOT", 7000.0)], MES_MULT, MES_TICK)
    assert m.entry_fill_price is None
    assert m.closed is False


def test_row_without_entry_order_id_is_not_touched():
    t = _trade()
    t["strategy_params"] = json.dumps({})
    m = match_fills(t, [_exec(5, "BOT", 7707.75)], MES_MULT, MES_TICK)
    assert m.entry_fill_price is None


# -- DB-level ---------------------------------------------------------------


def _db(tmp_path: Path) -> str:
    path = str(tmp_path / "ledger.db")
    with sqlite3.connect(path) as c:
        c.execute(
            """CREATE TABLE paper_trades (
                id INTEGER PRIMARY KEY, trade_id TEXT, symbol TEXT, side TEXT,
                quantity REAL, entry_price REAL, exit_price REAL, entry_time TEXT,
                exit_time TEXT, pnl REAL, status TEXT, account_id TEXT,
                stop_order_id TEXT, target_order_id TEXT, bracket_status TEXT,
                slippage_ticks REAL, strategy_params TEXT)"""
        )
        c.execute(
            """INSERT INTO paper_trades (trade_id, symbol, side, quantity, entry_price,
                entry_time, status, account_id, stop_order_id, target_order_id,
                bracket_status, strategy_params)
               VALUES ('e1adfa09','MES','buy',1,7704.75,'2026-10-27T08:51:31+00:00',
                'open','A','6','7','attached',?)""",
            (json.dumps({"source": "approval_queue", "entry_order_id": "5"}),),
        )
    return path


def _row(path):
    with sqlite3.connect(path) as c:
        c.row_factory = sqlite3.Row
        return dict(c.execute("select * from paper_trades").fetchone())


def test_sync_writes_entry_fill_then_close_idempotently(tmp_path):
    path = _db(tmp_path)
    entry = [_exec(5, "BOT", 7707.75)]
    r1 = sync_ledger_from_executions(path, entry, lambda s: MES_MULT, lambda s: MES_TICK)
    assert r1["entries_synced"] == 1
    row = _row(path)
    assert row["entry_price"] == 7707.75
    assert row["slippage_ticks"] == pytest.approx(12.0)
    assert row["status"] == "open"
    params = json.loads(row["strategy_params"])
    assert params["broker_account"] == "DUR303001"
    assert params["quoted_entry_price"] == 7704.75
    # logical kill-switch account id is NOT overwritten by the broker account
    assert row["account_id"] == "A"

    both = entry + [_exec(7, "SLD", 7708.75, t="2026-10-27 08:53:55+00:00")]
    r2 = sync_ledger_from_executions(path, both, lambda s: MES_MULT, lambda s: MES_TICK)
    assert r2["closes_synced"] == 1
    row = _row(path)
    assert row["status"] == "closed"
    assert row["exit_price"] == 7708.75
    assert row["pnl"] == pytest.approx(3.76)
    # quoted price survives re-sync; slippage is not recomputed off the fill
    assert json.loads(row["strategy_params"])["quoted_entry_price"] == 7704.75
    assert row["slippage_ticks"] == pytest.approx(12.0)

    r3 = sync_ledger_from_executions(path, both, lambda s: MES_MULT, lambda s: MES_TICK)
    assert r3["entries_synced"] == 0 and r3["closes_synced"] == 0


def test_sync_reports_flat_broker_open_ledger_mismatch(tmp_path):
    """Exit fills exist for the bracket but cover less than the entry qty while
    the ledger still says open -> surfaced as a mismatch for alerting."""
    path = _db(tmp_path)
    with sqlite3.connect(path) as c:
        c.execute("update paper_trades set quantity=2")
    execs = [_exec(5, "BOT", 7700.0, qty=2.0), _exec(6, "SLD", 7690.0, qty=1.0)]
    r = sync_ledger_from_executions(path, execs, lambda s: MES_MULT, lambda s: MES_TICK)
    assert r["closes_synced"] == 0
    assert r["partial_exits"] == ["e1adfa09"]


def test_is_broker_managed():
    from execution.ledger_fill_sync import is_broker_managed

    assert is_broker_managed({"stop_order_id": "6"}) is True
    assert is_broker_managed({"stop_order_id": None}) is False
    assert is_broker_managed({"stop_order_id": ""}) is False
    assert is_broker_managed({}) is False


class _FakeGateway:
    def __init__(self, execs, connected=True):
        self._execs = execs
        self._connected = connected
        self.calls = 0

    def is_connected(self):
        return self._connected

    async def get_executions(self):
        self.calls += 1
        return list(self._execs)


def test_run_once_skips_simulator_gateway(tmp_path):
    import asyncio

    from execution.ledger_fill_sync import run_fill_sync_once

    class _Sim:
        def is_connected(self):
            return True

    assert asyncio.run(run_fill_sync_once(_Sim(), _db(tmp_path))) is None


def test_run_once_skips_when_disconnected(tmp_path):
    import asyncio

    from execution.ledger_fill_sync import run_fill_sync_once

    gw = _FakeGateway([_exec(5, "BOT", 7707.75)], connected=False)
    assert asyncio.run(run_fill_sync_once(gw, _db(tmp_path))) is None
    assert gw.calls == 0


def test_run_once_syncs_real_gateway_executions(tmp_path):
    import asyncio

    from execution.ledger_fill_sync import run_fill_sync_once

    path = _db(tmp_path)
    gw = _FakeGateway(
        [_exec(5, "BOT", 7707.75), _exec(7, "SLD", 7708.75, t="2026-10-27 08:53:55+00:00")]
    )
    result = asyncio.run(run_fill_sync_once(gw, path))
    assert result["entries_synced"] == 1 and result["closes_synced"] == 1
    assert _row(path)["pnl"] == pytest.approx(3.76)
