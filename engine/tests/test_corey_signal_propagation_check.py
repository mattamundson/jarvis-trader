"""Branch tests for the Corey signal-propagation guardrail.

Exercises the verdict logic in scripts.corey_signal_propagation_check.collect()
with synthetic two-DB fixtures so the MISS / ok / scar / n-a / insufficient
branches are verified by data, not just by reading the code. (The live check
only ever exercised the "no eligible data" path.)
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

from scripts.corey_signal_propagation_check import MIN_ELIGIBLE, collect


def _mk_feedback_db(path, trades):
    """trades: list of (symbol, day:date, corey_signal)."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE trade_outcomes "
        "(trade_id TEXT, timestamp TEXT, symbol TEXT, corey_signal REAL)"
    )
    for i, (sym, day, sig) in enumerate(trades):
        # 18:00Z keeps UTC date == local date for any US tz.
        ts = f"{day.isoformat()}T18:00:00+00:00"
        conn.execute(
            "INSERT INTO trade_outcomes VALUES (?,?,?,?)",
            (f"t{i}", ts, sym, sig),
        )
    conn.commit()
    conn.close()


def _mk_trader_db(path, biases):
    """biases: list of (day:date, directional_bias, data_quality)."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE corey_session_bias "
        "(date TEXT, directional_bias TEXT, data_quality TEXT, conviction REAL)"
    )
    for day, bias, dq in biases:
        conn.execute(
            "INSERT INTO corey_session_bias VALUES (?,?,?,?)",
            (day.isoformat(), bias, dq, 0.65),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def dbs(tmp_path):
    return str(tmp_path / "feedback.db"), str(tmp_path / "trader.db")


def _days(n):
    today = date.today()
    return [today - timedelta(days=i) for i in range(n)]


def test_regression_when_all_eligible_zero(dbs):
    """>= MIN_ELIGIBLE post-cutoff directional-day futures trades, ALL zero -> regression."""
    fb, tr = dbs
    days = _days(MIN_ELIGIBLE)  # today .. today-(N-1)
    since = (date.today() - timedelta(days=30)).isoformat()
    _mk_feedback_db(fb, [("MES", d, 0.0) for d in days])
    _mk_trader_db(tr, [(d, "bearish", "fresh") for d in days])

    res = collect(days=60, since=since, feedback_db=fb, trader_db=tr)

    assert res["regression"] is True
    assert len(res["eligible_post"]) == MIN_ELIGIBLE
    assert len(res["misses"]) == MIN_ELIGIBLE
    assert len(res["nonzero"]) == 0


def test_healthy_when_at_least_one_nonzero(dbs):
    """One captured non-zero among the eligible trades -> NOT a regression."""
    fb, tr = dbs
    days = _days(MIN_ELIGIBLE)
    since = (date.today() - timedelta(days=30)).isoformat()
    sigs = [0.0] * (MIN_ELIGIBLE - 1) + [-0.5]
    _mk_feedback_db(fb, [("MES", d, s) for d, s in zip(days, sigs, strict=True)])
    _mk_trader_db(tr, [(d, "bearish", "fresh") for d in days])

    res = collect(days=60, since=since, feedback_db=fb, trader_db=tr)

    assert res["regression"] is False
    assert len(res["nonzero"]) == 1
    assert len(res["eligible_post"]) == MIN_ELIGIBLE


def test_scar_pre_cutoff_zeros_not_flagged(dbs):
    """Directional-day zeros BEFORE the go-live cutoff are scars, never regressions."""
    fb, tr = dbs
    days = _days(MIN_ELIGIBLE + 1)[1:]  # yesterday and older
    since = date.today().isoformat()  # everything before today is a scar
    _mk_feedback_db(fb, [("MES", d, 0.0) for d in days])
    _mk_trader_db(tr, [(d, "bearish", "fresh") for d in days])

    res = collect(days=60, since=since, feedback_db=fb, trader_db=tr)

    assert res["regression"] is False
    assert res["eligible_post"] == []
    assert all(r["verdict"] == "scar" for r in res["rows"])


def test_na_when_day_not_directional(dbs):
    """Zero corey_signal on a neutral/non-fresh day is expected -> n/a, never counted."""
    fb, tr = dbs
    days = _days(MIN_ELIGIBLE)
    since = (date.today() - timedelta(days=30)).isoformat()
    _mk_feedback_db(fb, [("MES", d, 0.0) for d in days])
    # neutral bias -> not eligible
    _mk_trader_db(tr, [(d, "neutral", "none") for d in days])

    res = collect(days=60, since=since, feedback_db=fb, trader_db=tr)

    assert res["regression"] is False
    assert res["eligible_post"] == []
    assert all(r["verdict"] == "n/a" for r in res["rows"])


def test_insufficient_sample_not_flagged(dbs):
    """Fewer than MIN_ELIGIBLE eligible trades cannot trigger a regression."""
    fb, tr = dbs
    days = _days(MIN_ELIGIBLE - 1)  # one short of the threshold
    since = (date.today() - timedelta(days=30)).isoformat()
    _mk_feedback_db(fb, [("MES", d, 0.0) for d in days])
    _mk_trader_db(tr, [(d, "bearish", "fresh") for d in days])

    res = collect(days=60, since=since, feedback_db=fb, trader_db=tr)

    assert res["regression"] is False
    assert len(res["eligible_post"]) == MIN_ELIGIBLE - 1
    assert len(res["misses"]) == MIN_ELIGIBLE - 1  # they're MISSes, just too few


def test_non_futures_symbol_ignored(dbs):
    """Equity symbols Corey doesn't cover are excluded entirely."""
    fb, tr = dbs
    days = _days(MIN_ELIGIBLE)
    since = (date.today() - timedelta(days=30)).isoformat()
    _mk_feedback_db(fb, [("QQQ", d, 0.0) for d in days])
    _mk_trader_db(tr, [(d, "bearish", "fresh") for d in days])

    res = collect(days=60, since=since, feedback_db=fb, trader_db=tr)

    assert res["rows"] == []
    assert res["regression"] is False
