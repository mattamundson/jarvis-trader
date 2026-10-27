"""
Tests for engine/risk/equity_basis.py and its use by PnLMonitor.

The max-drawdown kill switch must measure money the IB paper account actually
made or lost. As of 2026-10-27 the ledger held 91 closed rows booked by the
in-process simulator (+$4,426.57) and 1 broker-confirmed row (+$3.78), and the
drawdown peak came from daily_pnl history built on the simulated balance
($15,415.68). Switching only the equity to broker-confirmed rows would read
(10,003.78 - 15,415.68) / 15,415.68 = -35% and trip a false halt, so the peak
must come from the same broker-confirmed curve. Thresholds are NOT touched.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from risk.equity_basis import broker_confirmed_equity_state

INITIAL = 10_000.0


def _db(tmp_path: Path, rows) -> str:
    path = str(tmp_path / "basis.db")
    with sqlite3.connect(path) as c:
        c.execute(
            """CREATE TABLE paper_trades (
                id INTEGER PRIMARY KEY, trade_id TEXT, status TEXT, pnl REAL,
                exit_time TEXT, stop_order_id TEXT, bracket_status TEXT)"""
        )
        c.executemany(
            "INSERT INTO paper_trades (trade_id, status, pnl, exit_time, stop_order_id, "
            "bracket_status) VALUES (?,?,?,?,?,?)",
            rows,
        )
    return path


SIMULATED_WIN = ("sim-1", "closed", 4426.57, "2026-09-01T15:00:00+00:00", None, None)
CERT = ("cert-347", "closed", 3.78, "2026-10-27T08:53:55+00:00", "6", "attached")


def test_simulated_rows_excluded_from_equity_and_peak(tmp_path):
    s = broker_confirmed_equity_state(_db(tmp_path, [SIMULATED_WIN, CERT]), INITIAL)
    assert s.equity == pytest.approx(10_003.78)
    assert s.peak == pytest.approx(10_003.78)
    assert s.drawdown_pct == pytest.approx(0.0)
    assert s.trade_count == 1


def test_peak_follows_broker_curve_and_drawdown_is_negative(tmp_path):
    rows = [
        ("a", "closed", 500.0, "2026-10-28T10:00:00+00:00", "11", "attached"),
        ("b", "closed", -300.0, "2026-10-28T12:00:00+00:00", "21", "attached"),
    ]
    s = broker_confirmed_equity_state(_db(tmp_path, rows), INITIAL)
    assert s.peak == pytest.approx(10_500.0)
    assert s.equity == pytest.approx(10_200.0)
    assert s.drawdown_pct == pytest.approx((10_200.0 - 10_500.0) / 10_500.0)


def test_peak_never_below_initial_capital(tmp_path):
    rows = [("a", "closed", -400.0, "2026-10-28T10:00:00+00:00", "11", "attached")]
    s = broker_confirmed_equity_state(_db(tmp_path, rows), INITIAL)
    assert s.peak == pytest.approx(INITIAL)
    assert s.drawdown_pct == pytest.approx(-0.04)


def test_daily_pnl_counts_only_todays_broker_closes(tmp_path):
    rows = [
        ("a", "closed", -50.0, "2026-10-28T10:00:00+00:00", "11", "attached"),
        ("b", "closed", 20.0, "2026-10-29T10:00:00+00:00", "21", "attached"),
        ("sim", "closed", -999.0, "2026-10-29T11:00:00+00:00", None, None),
    ]
    s = broker_confirmed_equity_state(_db(tmp_path, rows), INITIAL, today="2026-10-29")
    assert s.daily_pnl == pytest.approx(20.0)


def test_open_phantom_and_null_pnl_rows_ignored(tmp_path):
    rows = [
        ("o", "open", None, None, "11", "attached"),
        ("p", "phantom", -12320.24, "2026-10-26T12:00:00+00:00", None, None),
        ("n", "closed", None, "2026-10-28T10:00:00+00:00", "31", "attached"),
    ]
    s = broker_confirmed_equity_state(_db(tmp_path, rows), INITIAL)
    assert s.equity == pytest.approx(INITIAL)
    assert s.trade_count == 0


# -- PnLMonitor integration -------------------------------------------------


class _HistoryDB:
    """daily_pnl history built on the simulated balance (the 2026-10-27 shape)."""

    def get_daily_pnl(self, start_date=None, end_date=None, days=None):
        return [{"ending_balance": 15_415.68, "starting_balance": 14_426.57}]


def test_pnl_monitor_drawdown_uses_basis_not_simulated_history(tmp_path):
    from risk.pnl_monitor import PnLMonitor

    path = _db(tmp_path, [SIMULATED_WIN, CERT])
    mon = PnLMonitor(
        db_manager=_HistoryDB(),
        starting_balance=INITIAL,
        equity_basis=lambda: broker_confirmed_equity_state(path, INITIAL),
    )
    # Without the basis this reads ~ -0.35 and trips the -20% halt.
    assert mon.get_drawdown_pct() == pytest.approx(0.0)


def test_pnl_monitor_basis_failure_falls_back_to_legacy_path(tmp_path):
    """A basis read error must not silently zero the drawdown; it falls back to
    the pre-existing computation (fail toward the old, more conservative read)."""
    from risk.pnl_monitor import PnLMonitor

    def _broken():
        raise sqlite3.OperationalError("db locked")

    legacy = PnLMonitor(db_manager=_HistoryDB(), starting_balance=INITIAL)
    mon = PnLMonitor(db_manager=_HistoryDB(), starting_balance=INITIAL, equity_basis=_broken)
    assert mon.get_drawdown_pct() == pytest.approx(legacy.get_drawdown_pct())

