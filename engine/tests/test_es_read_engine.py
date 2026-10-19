"""Tests for the observation-only ES read engine."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from database.migrations import run_migrations
from experiments import es_read_engine as ere
from experiments.mes_session_outcome import fill_outcomes

FIXTURE = Path(__file__).parent / "fixtures" / "es_read_5m_bars.csv"
SESSION = date(2026, 10, 16)


def _bars() -> pd.DataFrame:
    df = pd.read_csv(FIXTURE)
    df.index = pd.to_datetime(df.pop("timestamp"), utc=True)
    return df


def _gex(**kw):
    base = dict(contract="ESZ26", spot=6012.0, call_wall=6050.0, put_wall=5950.0,
                gamma_flip=6005.0, net_gex="-$1.00B", delayed=True,
                fetched_at=datetime(2026, 10, 16, 13, 25, tzinfo=timezone.utc))
    base.update(kw)
    return SimpleNamespace(**base)


def _bars_fn(df):
    async def fn(_symbol):
        return df
    return fn


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    with sqlite3.connect(path) as conn:
        run_migrations(conn)
    return path


def _ct_index(df):
    return ere._to_ct(df)


class TestLevelsAndPlan:
    def test_collect_levels_from_fixture(self):
        levels = ere.collect_levels(_ct_index(_bars()), SESSION, _gex())
        assert levels["ib_high"] == 6010 and levels["ib_low"] == 5990
        assert levels["on_high"] == 6020 and levels["on_low"] == 5998
        assert levels["flip"] == 6005 and levels["call_wall"] == 6050

    def test_long_plan_above_flip(self):
        levels = ere.collect_levels(_ct_index(_bars()), SESSION, _gex())
        plan = ere.build_plan(levels, 6012.0)
        assert plan.side == "long"
        assert (plan.trigger, plan.trigger_source) == (6020, "on_high")
        assert (plan.invalidation, plan.invalidation_source) == (6010, "ib_high")

    def test_short_plan_below_flip(self):
        levels = {"flip": 6005.0, "ib_low": 5990.0, "on_high": 6020.0}
        plan = ere.build_plan(levels, 6000.0)
        assert plan.side == "short"
        assert plan.trigger == 5990 and plan.invalidation == 6005

    @pytest.mark.parametrize(
        "levels,price,reason",
        [
            ({"flip": 6005.0, "on_high": 6020.0}, None, "no_price_at_lock"),
            ({"on_high": 6020.0, "on_low": 5990.0}, 6000.0, "no_gamma_flip"),
            ({"flip": 5990.0}, 6000.0, "no_level_on_both_sides"),
        ],
    )
    def test_skip_cases(self, levels, price, reason):
        plan = ere.build_plan(levels, price)
        assert plan.side == "skip" and plan.reason == reason


class TestScoring:
    def _plan(self):
        return ere.ReadPlan("long", "x", 6012.0, 6020.0, "on_high", 6010.0, "ib_high")

    def test_confirmed_win(self):
        out = ere.score_plan(self._plan(), _ct_index(_bars()), SESSION)
        assert out.status == "confirmed_win"
        assert out.entry == 6023 and out.exit == 6040 and out.delta == 17

    def test_single_close_does_not_confirm(self):
        df = _bars()
        ts = pd.Timestamp("2026-10-16 09:05", tz="America/Chicago").tz_convert("UTC")
        df.loc[ts, "close"] = 6018.0
        df.loc[df.index > ts, "close"] = 6015.0
        out = ere.score_plan(self._plan(), _ct_index(df), SESSION)
        assert out.status == "no_trigger" and out.delta == 0.0

    def test_invalidated_before_confirmation(self):
        df = _bars()
        ts = pd.Timestamp("2026-10-16 08:45", tz="America/Chicago").tz_convert("UTC")
        df.loc[ts, "close"] = 6008.0
        out = ere.score_plan(self._plan(), _ct_index(df), SESSION)
        assert out.status == "invalidated" and out.entry is None

    def test_exit_on_invalidation_after_entry(self):
        df = _bars()
        ts = pd.Timestamp("2026-10-16 11:00", tz="America/Chicago").tz_convert("UTC")
        df.loc[df.index >= ts, "close"] = 6005.0
        out = ere.score_plan(self._plan(), _ct_index(df), SESSION)
        assert out.status == "confirmed_loss"
        assert out.exit_reason == "invalidation_close" and out.delta == -18

    def test_no_bars(self):
        assert ere.score_plan(self._plan(), None, SESSION).status == "no_data"


class TestPortGuard:
    def test_paper_port_ok(self):
        assert ere.ib_data_port_ok(SimpleNamespace(IBKR_PORT=4002, IBKR_MARKET_DATA_PORT=None))

    def test_live_data_port_refused(self):
        assert not ere.ib_data_port_ok(SimpleNamespace(IBKR_PORT=4002, IBKR_MARKET_DATA_PORT=4001))
        assert not ere.ib_data_port_ok(SimpleNamespace(IBKR_PORT=4001, IBKR_MARKET_DATA_PORT=None))

    async def test_live_port_skips_bar_fetch(self, db):
        class DM:
            called = False

            async def get_bars(self, *a, **k):
                DM.called = True
                return _bars()

        res = await ere.lock_read(for_date=SESSION, db_path=db, data_manager=DM(),
                                  gex_fn=_gex, cfg=SimpleNamespace(IBKR_PORT=4001))
        assert not DM.called
        assert "ib_port_not_paper" in res["warnings"]
        assert res["plan"]["side"] == "skip"


class TestStorage:
    async def test_lock_then_score_via_outcome_job(self, db):
        fn = _bars_fn(_bars())
        res = await ere.lock_read(for_date=SESSION, db_path=db, bars_fn=fn, gex_fn=_gex)
        assert res["inserted"] and res["plan"]["trigger"] == 6020

        again = await ere.lock_read(for_date=SESSION, db_path=db, bars_fn=fn, gex_fn=_gex)
        assert not again["inserted"]

        result = await fill_outcomes(for_date=SESSION, db_path=db, bars_fn=fn)
        assert result.updated_rows == 1

        with sqlite3.connect(db) as conn:
            row = conn.execute(
                "SELECT entry_hypothesis_side, open_price, outcome_delta, gamma_snapshot_json "
                "FROM mes_session_hypothesis WHERE symbol = ?", (ere.READ_SYMBOL,)
            ).fetchone()
        assert row[0] == "long" and row[1] == 6012 and row[2] == 17
        payload = json.loads(row[3])
        assert payload["plan"]["invalidation"] == 6010
        assert payload["outcome"]["status"] == "confirmed_win"

    async def test_zerogex_down_records_skip(self, db):
        res = await ere.lock_read(for_date=SESSION, db_path=db,
                                  bars_fn=_bars_fn(_bars()), gex_fn=lambda: None)
        assert res["inserted"]
        assert res["plan"]["reason"] == "no_gamma_flip"
        assert "zerogex_unavailable" in res["warnings"]


def test_module_has_no_order_path():
    src = Path(ere.__file__).read_text(encoding="utf-8")
    for token in ("place_order", "placeOrder", "submit_order", "ib_gateway", "safety_layer"):
        assert token not in src
