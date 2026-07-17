"""Tests for scripts/gapfill_options_papertrack.py — LONG_GAP_FILL options
paper-track logger. Pure fixtures, no network, no live DB."""

import json
import sqlite3
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from analysis.options_implied import Contract
from scripts.gapfill_options_papertrack import (
    fetch_gapfill_trades,
    leg_snapshot,
    load_records,
    process,
    save_records,
    select_spread,
)

_CT = ZoneInfo("America/Chicago")
TODAY = date(2026, 7, 16)
NOW = datetime(2026, 7, 16, 10, 0, tzinfo=_CT)


def _call(strike, expiry=TODAY, bid=1.0, ask=1.2):
    return Contract(
        root="SPY", expiry=expiry, right="C", strike=strike,
        bid=bid, ask=ask, mid=(bid + ask) / 2, last_trade=None,
        iv=0.15, delta=0.5, open_interest=100, volume=10,
    )


def _chain(spot=628.0):
    contracts = [_call(k) for k in (625.0, 626.0, 627.0, 628.0, 629.0, 630.0, 631.0, 632.0)]
    # a later expiry that must NOT be picked while a nearer one exists
    contracts.append(_call(628.0, expiry=date(2026, 7, 17)))
    return spot, 1752670000, contracts


def _trade(tid="t-1", entry=6280.0, target=6310.0, exit_time=None, exit_price=None):
    return {
        "trade_id": tid, "symbol": "MES", "side": "buy",
        "entry_price": entry, "exit_price": exit_price,
        "entry_time": "2026-07-16T14:35:00+00:00", "exit_time": exit_time,
        "status": "closed" if exit_time else "open",
        "stop_loss": entry - 15.0, "take_profit": target,
    }


class TestSelectSpread:
    def test_strike_and_width_mapping(self):
        spot, _, contracts = _chain()
        spread = select_spread(contracts, spot, _trade(), TODAY)
        # entry 6280 -> ATM 628; target +30 MES pts -> width 3 SPY dollars
        assert spread["k_long"] == 628.0
        assert spread["k_short"] == 631.0
        assert spread["expiry"] == TODAY.isoformat()

    def test_width_floor_is_one_dollar(self):
        spot, _, contracts = _chain()
        spread = select_spread(contracts, spot, _trade(target=6284.0), TODAY)
        assert spread["k_short"] == 629.0

    def test_missing_target_uses_half_pct_fallback(self):
        spot, _, contracts = _chain()
        spread = select_spread(contracts, spot, _trade(target=None), TODAY)
        assert spread["k_short"] == 631.0  # round(628*0.005)=3

    def test_no_future_expiry_returns_none(self):
        spot, _, contracts = _chain()
        assert select_spread(contracts, spot, _trade(), date(2027, 1, 1)) is None


class TestLegSnapshot:
    def test_cross_and_mid_brackets(self):
        spot, qts, contracts = _chain()
        spread = select_spread(contracts, spot, _trade(), TODAY)
        snap = leg_snapshot(spread, spot, qts, "2026-07-16T10:00:00")
        # identical synthetic quotes on both legs: cross debit = ask - bid
        assert snap["debit_cross"] == pytest.approx(0.2)
        assert snap["credit_cross"] == pytest.approx(-0.2)
        assert snap["value_mid"] == pytest.approx(0.0)


class TestProcessLifecycle:
    def test_entry_recorded_for_new_trade(self):
        records = {}
        n_entry, n_exit, changed = process([_trade()], records, _chain(), NOW)
        assert (n_entry, n_exit, changed) == (1, 0, True)
        rec = records["t-1"]
        assert rec["quality"] == "open"
        assert rec["entry_leg"]["debit_cross"] is not None
        assert "exit_leg" not in rec

    def test_exit_recorded_and_returns_computed(self):
        records = {}
        process([_trade()], records, _chain(), NOW)
        closed = _trade(exit_time="2026-07-16T19:55:00+00:00", exit_price=6305.0)
        n_entry, n_exit, changed = process([closed], records, _chain(), NOW)
        rec = records["t-1"]
        assert (n_entry, n_exit) == (0, 1)
        assert rec["quality"] == "complete"
        assert rec["futures_exit_price"] == 6305.0
        # cross: debit 0.2 -> credit -0.2 => ret -2.0
        assert rec["ret_cross"] == pytest.approx(-2.0)
        # mid value is 0.0 at entry (identical synthetic quotes), so the
        # mid-bracket return is undefined (debit <= 0) and must be absent.
        assert "ret_mid" not in rec

    def test_exit_after_expiry_marks_missed(self):
        records = {}
        process([_trade()], records, _chain(), NOW)
        closed = _trade(exit_time="2026-07-17T19:55:00+00:00", exit_price=6305.0)
        later = datetime(2026, 7, 20, 10, 0, tzinfo=_CT)
        process([closed], records, _chain(), later)
        assert records["t-1"]["quality"] == "missed_exit"
        assert "ret_cross" not in records["t-1"]

    def test_degraded_chain_leaves_trade_pending(self):
        records = {}
        n_entry, n_exit, changed = process([_trade()], records, None, NOW)
        assert (n_entry, n_exit, changed) == (0, 0, False)
        assert records == {}


class TestDbFilter:
    def test_fetch_filters_signal_symbol_and_side(self, tmp_path):
        db = tmp_path / "t.db"
        con = sqlite3.connect(db)
        con.execute(
            "CREATE TABLE paper_trades (trade_id TEXT, symbol TEXT, side TEXT,"
            " entry_price REAL, exit_price REAL, entry_time TEXT, exit_time TEXT,"
            " status TEXT, stop_loss REAL, take_profit REAL, strategy_params TEXT)"
        )
        rows = [
            ("a", "MES", "buy", json.dumps({"stark_signal": "LONG_GAP_FILL"})),
            ("b", "MES", "sell", json.dumps({"stark_signal": "LONG_GAP_FILL"})),
            ("c", "MES", "buy", json.dumps({"stark_signal": "SHORT_GAP_FILL"})),
            ("d", "MGC", "buy", json.dumps({"stark_signal": "LONG_GAP_FILL"})),
            ("e", "MES", "buy", json.dumps({"source": "scanner"})),
        ]
        for tid, sym, side, params in rows:
            con.execute(
                "INSERT INTO paper_trades VALUES (?,?,?,6280,NULL,"
                "'2026-07-16T14:35:00',NULL,'open',6265,6310,?)",
                (tid, sym, side, params),
            )
        con.commit()
        con.close()
        got = fetch_gapfill_trades(db)
        assert [t["trade_id"] for t in got] == ["a"]


class TestJsonlRoundTrip:
    def test_save_load(self, tmp_path):
        path = tmp_path / "track.jsonl"
        records = {"t-1": {"trade_id": "t-1", "quality": "open"}}
        save_records(records, path)
        assert load_records(path) == records
