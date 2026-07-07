"""
Unit tests — Paper Stop-Loss Monitor (Initiative 1, Track A) and the
paper_runner data-starvation guard (A1).

Pure-helper tests need no engine state. The check_once() tests drive the
monitor with in-memory fakes for db_manager / data_manager, so they exercise
the breach → close → alert path (and the race / no-stop / unavailable-price
branches) without touching SQLite or any live feed.

Run with the engine venv:
    engine/.venv/Scripts/python.exe -m pytest engine/tests/test_paper_stop_monitor.py -q
"""

import asyncio
import pathlib
import sys

# No conftest on this path — put engine/ on sys.path so `services.*` / `backtest.*` import.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backtest.paper_runner import should_alert_data_error  # noqa: E402
from services.paper_stop_monitor import (  # noqa: E402
    PaperStopMonitor,
    compute_stop_pnl,
    is_stop_breached,
    multiplier_for,
    normalize_side,
)

# ── Pure helpers ───────────────────────────────────────────────────────────────

def test_normalize_side_aliases():
    assert normalize_side("buy") == "long"
    assert normalize_side("BUY") == "long"
    assert normalize_side("long") == "long"
    assert normalize_side("b") == "long"
    assert normalize_side("sell") == "short"
    assert normalize_side("SHORT") == "short"
    assert normalize_side("s") == "short"
    # Unknown encodings pass through lower-cased (caller treats as "can't evaluate").
    assert normalize_side("flat") == "flat"
    assert normalize_side(None) == ""


def test_is_stop_breached_long():
    # Long is breached when price <= stop.
    assert is_stop_breached("long", 100.0, 99.99) is True
    assert is_stop_breached("long", 100.0, 100.0) is True
    assert is_stop_breached("long", 100.0, 100.01) is False
    # side='buy' (the trade #178 encoding) must behave as long.
    assert is_stop_breached("buy", 4497.51, 4490.0) is True
    assert is_stop_breached("buy", 4497.51, 4500.0) is False


def test_is_stop_breached_short():
    # Short is breached when price >= stop.
    assert is_stop_breached("short", 100.0, 100.01) is True
    assert is_stop_breached("short", 100.0, 100.0) is True
    assert is_stop_breached("short", 100.0, 99.99) is False
    assert is_stop_breached("sell", 100.0, 105.0) is True


def test_is_stop_breached_missing_inputs():
    assert is_stop_breached("long", None, 100.0) is False
    assert is_stop_breached("long", 100.0, None) is False
    assert is_stop_breached("flat", 100.0, 50.0) is False  # unknown side


def test_compute_stop_pnl():
    # Long, adverse move down 10 pts, 1 contract, $10/pt → −$100.
    assert compute_stop_pnl("long", 100.0, 90.0, 1, 10.0) == -100.0
    # Short, favorable move down 10 pts → +$100.
    assert compute_stop_pnl("short", 100.0, 90.0, 1, 10.0) == 100.0
    # qty scales linearly; 'buy' normalizes to long.
    assert compute_stop_pnl("buy", 100.0, 95.0, 2, 5.0) == -50.0
    # MGC trade #178 shape: entry 4503.9 → exit 4497.51, $10/pt → ≈ −$63.90.
    assert compute_stop_pnl("buy", 4503.9, 4497.51, 1, 10.0) == -63.9


def test_multiplier_for():
    assert multiplier_for("MGC") == 10.0
    assert multiplier_for("MES") == 5.0
    assert multiplier_for("MNQ") == 2.0
    assert multiplier_for("MCL") == 100.0
    assert multiplier_for("ZZZZ") == 1.0  # unknown → neutral
    # paper_config override wins over the fallback map.
    assert multiplier_for("MGC", {"MGC": {"multiplier": 11.0}}) == 11.0


def test_should_alert_data_error():
    # Below threshold: silent.
    assert should_alert_data_error(0) is False
    assert should_alert_data_error(2) is False
    # First cross fires.
    assert should_alert_data_error(3) is True
    # Then quiet until the re-announce cadence.
    assert should_alert_data_error(4) is False
    assert should_alert_data_error(14) is False
    assert should_alert_data_error(15) is True  # 3 + 12
    assert should_alert_data_error(27) is True  # 3 + 24


# ── check_once() integration with fakes ─────────────────────────────────────────

class _FakeDB:
    def __init__(self, open_trades, close_returns=True):
        self._open = open_trades
        self._close_returns = close_returns
        self.close_calls = []

    def get_open_trades(self, symbol=None):
        return list(self._open)

    def close_paper_trade(self, trade_id, exit_price, exit_time=None, pnl=0.0):
        self.close_calls.append(
            {"trade_id": trade_id, "exit_price": exit_price, "pnl": pnl}
        )
        return self._close_returns


class _FakeData:
    def __init__(self, price, source="ibkr"):
        # source defaults to a LIVE tick tier so existing breach tests act as
        # before; the stale-data tests pass a non-live source explicitly.
        self._price = price
        self._source = source

    async def get_current_price(self, symbol, is_futures=False):
        if self._price is None:
            return {}
        return {"last_price": self._price, "source": self._source}


def _trade(**kw):
    base = {
        "trade_id": "t-178",
        "symbol": "MGC",
        "side": "buy",
        "entry_price": 4503.9,
        "quantity": 1,
        "stop_loss": 4497.51,
    }
    base.update(kw)
    return base


def test_check_once_fires_on_breach():
    db = _FakeDB([_trade()])
    mon = PaperStopMonitor(db, _FakeData(4490.0))
    fired = asyncio.run(mon.check_once())
    assert fired == 1
    assert len(db.close_calls) == 1
    call = db.close_calls[0]
    assert call["trade_id"] == "t-178"
    assert call["exit_price"] == 4490.0
    # Long, 4503.9 → 4490.0 = −13.9 pts * 1 * $10 = −$139.0
    assert call["pnl"] == -139.0


def test_check_once_no_breach_when_price_above_stop():
    db = _FakeDB([_trade()])
    mon = PaperStopMonitor(db, _FakeData(4500.0))  # above the 4497.51 stop
    fired = asyncio.run(mon.check_once())
    assert fired == 0
    assert db.close_calls == []


def test_check_once_race_noop_when_already_closed():
    # close_paper_trade returns False → the runner already closed it; not counted.
    db = _FakeDB([_trade()], close_returns=False)
    mon = PaperStopMonitor(db, _FakeData(4490.0))
    fired = asyncio.run(mon.check_once())
    assert fired == 0
    assert len(db.close_calls) == 1  # attempted, but idempotent UPDATE matched 0 rows


def test_check_once_skips_trade_without_stop_when_loss_under_cap():
    # A null-stop trade with only a SMALL unrealized loss is still left alone —
    # there is no stop to enforce and the catastrophe cap (default $750) is not
    # breached. price 4500 vs entry 4503.9 (MGC ×10) = -$39.
    db = _FakeDB([_trade(stop_loss=None)])
    mon = PaperStopMonitor(db, _FakeData(4500.0))
    fired = asyncio.run(mon.check_once())
    assert fired == 0
    assert db.close_calls == []


def test_check_once_max_loss_backstop_fires_on_null_stop():
    # The -$5,440 MES / -$1,284 MGC class: a position with NO recorded stop whose
    # live loss blows past the catastrophe cap must be force-closed. price 4400 vs
    # entry 4503.9 (MGC ×10) = -$1,039, beyond the default $750 cap.
    db = _FakeDB([_trade(stop_loss=None)])
    mon = PaperStopMonitor(db, _FakeData(4400.0))
    fired = asyncio.run(mon.check_once())
    assert fired == 1
    assert len(db.close_calls) == 1
    assert db.close_calls[0]["pnl"] <= -750.0


def test_check_once_max_loss_backstop_disabled_restores_skip():
    # PAPER_MAX_LOSS_USD_PER_TRADE=0 turns the backstop off → a null-stop trade is
    # skipped no matter how large the loss (legacy behavior).
    import os as _os

    prev = _os.environ.get("PAPER_MAX_LOSS_USD_PER_TRADE")
    _os.environ["PAPER_MAX_LOSS_USD_PER_TRADE"] = "0"
    try:
        db = _FakeDB([_trade(stop_loss=None)])
        mon = PaperStopMonitor(db, _FakeData(100.0))  # catastrophic vs 4503.9 entry
        fired = asyncio.run(mon.check_once())
        assert fired == 0
        assert db.close_calls == []
    finally:
        if prev is None:
            _os.environ.pop("PAPER_MAX_LOSS_USD_PER_TRADE", None)
        else:
            _os.environ["PAPER_MAX_LOSS_USD_PER_TRADE"] = prev


def test_check_once_skips_when_price_unavailable():
    db = _FakeDB([_trade()])
    mon = PaperStopMonitor(db, _FakeData(None))  # all tiers missed
    fired = asyncio.run(mon.check_once())
    assert fired == 0
    assert db.close_calls == []


def test_check_once_empty_book():
    db = _FakeDB([])
    mon = PaperStopMonitor(db, _FakeData(4490.0))
    assert asyncio.run(mon.check_once()) == 0


# ── Stale-data guard: a feed-independent backstop must not act on a frozen price ──

def test_check_once_skips_stale_csv_cache_source_even_when_breached():
    # Dark feed → get_current_price falls through to Tier 5 csv_cache (day-old
    # close). The price (4490) breaches the 4497.51 stop, but it is STALE, so the
    # monitor must NOT close — it defers to the A1 feed-dark alert instead of
    # firing/holding a stop on a frozen price (the #178 failure mode in reverse).
    db = _FakeDB([_trade()])
    mon = PaperStopMonitor(db, _FakeData(4490.0, source="csv_cache"))
    fired = asyncio.run(mon.check_once())
    assert fired == 0
    assert db.close_calls == []


def test_check_once_skips_ibkr_historical_source():
    # Tier 1 can return a historical last-close (source='ibkr_historical') with a
    # non-None price — also stale; must be skipped.
    db = _FakeDB([_trade()])
    mon = PaperStopMonitor(db, _FakeData(4490.0, source="ibkr_historical"))
    assert asyncio.run(mon.check_once()) == 0
    assert db.close_calls == []


def test_check_once_acts_on_each_live_source():
    # Every live tick tier the monitor's docstring promises must still enforce.
    for live in ("ibkr", "schwab", "tradingview", "polygon_stream"):
        db = _FakeDB([_trade()])
        mon = PaperStopMonitor(db, _FakeData(4490.0, source=live))
        fired = asyncio.run(mon.check_once())
        assert fired == 1, f"live source {live!r} must enforce the stop"
        assert len(db.close_calls) == 1


if __name__ == "__main__":  # allow plain `python test_paper_stop_monitor.py`
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
            print(f"PASS {fn.__name__}")
        except Exception:  # noqa: BLE001
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
