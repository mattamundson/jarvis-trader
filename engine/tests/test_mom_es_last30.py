"""Synthetic proof for MOM. No real bars and no Databento call."""

from __future__ import annotations

import math
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from research.mom_es_last30 import (
    ROUND_TRIP_COST,
    Bar,
    HoldoutClosed,
    ReplicationWindowError,
    assert_replication_window,
    best_five_share,
    build_sessions,
    cost_identity,
    ols_slope_newey_west_t,
    summarize,
)

CHICAGO = ZoneInfo("America/Chicago")
SCRIPT = Path(__file__).resolve().parents[1] / "research" / "mom_es_last30.py"


def bar(day: str, hour: int, minute: int, instrument: str, open_: float, close: float) -> Bar:
    year, month, dom = (int(part) for part in day.split("-"))
    return Bar(
        ts=datetime(year, month, dom, hour, minute, tzinfo=CHICAGO),
        instrument_id=instrument,
        open=open_,
        close=close,
    )


def session_bars(
    trade_day: str,
    prior_day: str,
    *,
    prior_instrument: str = "ESZ0",
    decision_instrument: str = "ESZ0",
    prior_settle: float = 100.0,
    close_1429: float = 101.0,
    open_1430: float = 101.0,
    close_1430: float = 101.0,
    close_1459: float = 50.0,
    settlement: float = 102.0,
) -> list[Bar]:
    return [
        bar(prior_day, 15, 0, prior_instrument, prior_settle, prior_settle),
        bar(trade_day, 14, 29, decision_instrument, close_1429, close_1429),
        bar(trade_day, 14, 30, decision_instrument, open_1430, close_1430),
        bar(trade_day, 14, 59, decision_instrument, close_1459, close_1459),
        bar(trade_day, 15, 0, decision_instrument, settlement, settlement),
    ]


def test_contract_change_is_dropped_and_same_contract_is_kept() -> None:
    changed = session_bars("2020-06-02", "2020-06-01", prior_instrument="ESM0", decision_instrument="ESU0")
    kept_bars = session_bars("2020-06-02", "2020-06-01")
    changed_sessions, changed_dropped = build_sessions(changed)
    kept_sessions, kept_dropped = build_sessions(kept_bars)
    assert changed_sessions == []
    assert changed_dropped == 1
    assert kept_dropped == 0
    assert len(kept_sessions) == 1
    assert kept_sessions[0].instrument_id == "ESZ0"
    print("PASS contract change dropped=1; same contract kept=1")


def test_signal_fill_and_settlement_prices() -> None:
    bars = session_bars(
        "2020-06-02",
        "2020-06-01",
        prior_settle=100.0,
        close_1429=110.0,
        open_1430=90.0,
        close_1430=80.0,
        close_1459=70.0,
        settlement=95.0,
    )
    sessions, dropped = build_sessions(bars)
    assert dropped == 0
    session = sessions[0]
    assert session.direction == 1
    assert session.signal_return == pytest.approx((110.0 - 100.0) / 100.0)
    assert session.forward_return == pytest.approx((95.0 - 90.0) / 90.0)
    assert session.net_pnl == pytest.approx(1 * (95.0 - 90.0) * 5.0 - ROUND_TRIP_COST)
    print(
        "PASS signal=14:29 close 110, fill=14:30 open 90, "
        f"exit=15:00 settlement 95, net={session.net_pnl:.2f}"
    )


def test_small_gross_win_is_a_net_loss_after_cost() -> None:
    bars = session_bars(
        "2020-06-02",
        "2020-06-01",
        prior_settle=100.0,
        close_1429=101.0,
        open_1430=100.0,
        settlement=100.5,
    )
    session = build_sessions(bars)[0][0]
    gross = 0.5 * 5.0
    assert gross == pytest.approx(2.50)
    assert session.net_pnl == pytest.approx(2.50 - 3.72)
    assert session.net_pnl < 0
    print(f"PASS gross {gross:.2f} -> net {session.net_pnl:.2f} after 3.72")


def test_newey_west_matches_hand_computed_slope_t() -> None:
    """n=4, lags=1. OLS slope is 0.8. Bartlett meat gives var(b)=0.0243.

    x = 1,2,3,4 and y = 1,3,2,4.
    det(X'X) = 20. Residuals = -0.3, 0.9, -0.9, 0.3.
    S = [[0.45, 1.125], [1.125, 3.42]].
    (X'X)^{-1} S (X'X)^{-1} slope variance = 0.0243.
    t = 0.8 / sqrt(0.0243).
    """
    hand_slope = 0.8
    hand_t = 0.8 / math.sqrt(0.0243)
    slope, t_stat = ols_slope_newey_west_t([1.0, 2.0, 3.0, 4.0], [1.0, 3.0, 2.0, 4.0], lags=1)
    assert slope == pytest.approx(hand_slope)
    assert t_stat == pytest.approx(hand_t)
    print(f"PASS Newey-West hand t={hand_t:.6f} observed t={t_stat:.6f}")


def test_replication_refuses_a_2021_bar() -> None:
    bars = session_bars("2021-01-04", "2020-12-31")
    with pytest.raises(ReplicationWindowError):
        assert_replication_window(bars)
    print("PASS replication raises on 2021-01-04")


def test_holdout_refuses_a_missing_sentinel() -> None:
    code = (
        "from pathlib import Path\n"
        "from research.mom_es_last30 import HoldoutClosed, execute\n"
        "try:\n"
        "    execute([], 'holdout', Path('missing-mom-sentinel.json'))\n"
        "except HoldoutClosed:\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(1)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=SCRIPT.parent.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    print("PASS holdout raises when the sentinel is missing")


def test_one_process_cannot_run_both_modes(tmp_path: Path) -> None:
    code = (
        "import os\n"
        "from pathlib import Path\n"
        "from datetime import datetime\n"
        "from zoneinfo import ZoneInfo\n"
        "from research.mom_es_last30 import Bar, ModeConflict, execute\n"
        "ct = ZoneInfo('America/Chicago')\n"
        "def b(day, hour, minute, px):\n"
        "    y, m, d = (int(p) for p in day.split('-'))\n"
        "    return Bar(datetime(y, m, d, hour, minute, tzinfo=ct), 'ESZ0', px, px)\n"
        "bars = [\n"
        "    b('2020-06-01', 15, 0, 100.0),\n"
        "    b('2020-06-02', 14, 29, 101.0),\n"
        "    b('2020-06-02', 14, 30, 101.0),\n"
        "    b('2020-06-02', 15, 0, 102.0),\n"
        "]\n"
        "sentinel = Path(os.environ['MOM_SENTINEL'])\n"
        "execute(bars, 'replication', sentinel)\n"
        "try:\n"
        "    execute(bars, 'holdout', sentinel)\n"
        "except ModeConflict:\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(1)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=SCRIPT.parent.parent,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "MOM_SENTINEL": str(tmp_path / "sentinel.json")},
    )
    assert completed.returncode == 0, completed.stderr
    print("PASS second mode in one process raises ModeConflict")


def test_cost_identity_and_best_five_share() -> None:
    text = cost_identity()
    assert "fees=1.22" in text
    assert "slippage=2.50" in text
    assert "round_trip=3.72" in text
    assert best_five_share([1.0, 2.0, 3.0, 4.0, 5.0, -10.0]) == pytest.approx(15.0 / 5.0)
    print(f"PASS {text}")


def test_script_source_does_not_download() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "get_range" not in source
    assert "jarvis_trader.db" not in source
    assert "timeseries" not in source
    print("PASS script source has no Databento get_range")


def test_inconclusive_when_fewer_than_three_sessions() -> None:
    bars = session_bars(
        "2020-06-02",
        "2020-06-01",
        open_1430=100.0,
        settlement=100.5,
        close_1429=101.0,
    )
    row = summarize(build_sessions(bars)[0])
    assert row.trade_count == 1
    assert row.net_mean == pytest.approx(2.50 - 3.72)
    assert row.verdict == "inconclusive"
    print(f"PASS one-trade row net_mean={row.net_mean:.2f} verdict={row.verdict}")


def test_holdout_closed_type_is_the_sentinel_error() -> None:
    assert issubclass(HoldoutClosed, RuntimeError)
