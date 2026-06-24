"""Unit tests for the ES-NQ spread DARK forward paper track (pure core only).

Covers the IO-free logic the forward record rests on:
  - step_position (the shared backtest/live primitive) -- exact parity with the batch path
  - decide_transition: open / hold / close / flip + no-spurious-trade on hold
  - close_trade: P&L sign + round-trip cost, build_windows-shaped output
  - align_latest: inner-join + latest-z, insufficient-overlap guard

Network/file IO (fetch_bars / run_once / report) is thin and exercised live, not here.
"""

from __future__ import annotations

import math

import numpy as np

from backtest import spread_backtest as sb
from backtest import spread_paper_track as pt

P = {"window": 40, "entry": 2.0, "exit": 0.5, "stop": 4.0}


# --- step_position parity with the batch generate_positions -----------------


def test_step_position_matches_batch():
    rng = np.random.default_rng(0)
    z = rng.normal(0, 1.5, 200)
    z[::17] = np.nan  # scatter NaNs (warm-up / zero-var analogue)
    batch = sb.generate_positions(z, 2.0, 0.5, 4.0)
    cur = 0
    for t in range(len(z)):
        cur = sb.step_position(cur, float(z[t]), 2.0, 0.5, 4.0)
        assert cur == batch[t]


# --- decide_transition -----------------------------------------------------


def test_transition_open_from_flat_short_spread():
    st = pt._empty_state()
    ns, ev, closed = pt.decide_transition(st, 2.5, 5000.0, 18000.0, "t1", P)
    assert ev == "open"
    assert ns["position"] == -1  # z>entry -> short spread
    assert ns["entry_es"] == 5000.0 and ns["entry_nq"] == 18000.0
    assert ns["entry_time"] == "t1"
    assert closed is None


def test_transition_open_from_flat_long_spread():
    st = pt._empty_state()
    ns, ev, _ = pt.decide_transition(st, -2.5, 5000.0, 18000.0, "t1", P)
    assert ev == "open" and ns["position"] == 1


def test_transition_hold_flat_records_no_trade():
    st = pt._empty_state()
    ns, ev, closed = pt.decide_transition(st, 1.0, 5000.0, 18000.0, "t1", P)
    assert ev == "hold" and ns["position"] == 0 and closed is None
    assert ns["last_bar_ts"] == "t1"


def test_transition_in_position_hold():
    st = {
        **pt._empty_state(),
        "position": -1,
        "entry_es": 5000.0,
        "entry_nq": 18000.0,
        "entry_time": "t0",
        "entry_z": 2.5,
    }
    ns, ev, closed = pt.decide_transition(st, 1.0, 5010.0, 18010.0, "t1", P)
    assert ev == "in_position" and ns["position"] == -1 and closed is None


def test_transition_close_on_reversion():
    st = {
        **pt._empty_state(),
        "position": -1,
        "entry_es": 5000.0,
        "entry_nq": 18000.0,
        "entry_time": "t0",
        "entry_z": 2.5,
    }
    ns, ev, closed = pt.decide_transition(st, 0.3, 5010.0, 18010.0, "t1", P)
    assert ev == "close" and ns["position"] == 0
    assert ns["entry_es"] is None
    assert closed is not None and closed["symbol"] == pt.SPREAD_SYMBOL
    assert closed["exit_time"] == "t1"


def test_transition_cannot_reverse_in_one_step():
    # The state machine only moves one level per bar (-1->0->+1), so a direct reversal
    # is impossible: from -1 with z=-2.5 (between exit and stop) it HOLDS, never flips.
    st = {
        **pt._empty_state(),
        "position": -1,
        "entry_es": 5000.0,
        "entry_nq": 18000.0,
        "entry_time": "t0",
        "entry_z": 2.5,
    }
    ns, ev, closed = pt.decide_transition(st, -2.5, 5010.0, 18010.0, "t1", P)
    assert ev == "in_position" and ns["position"] == -1 and closed is None


def test_transition_close_then_reopen_opposite_across_two_bars():
    # The realistic reversal path: exit to flat on reversion, then open the opposite side.
    st = {
        **pt._empty_state(),
        "position": -1,
        "entry_es": 5000.0,
        "entry_nq": 18000.0,
        "entry_time": "t0",
        "entry_z": 2.5,
    }
    s1, e1, c1 = pt.decide_transition(st, 0.3, 5010.0, 18010.0, "t1", P)  # exit
    assert e1 == "close" and s1["position"] == 0 and c1 is not None
    s2, e2, c2 = pt.decide_transition(s1, -2.5, 5010.0, 18010.0, "t2", P)  # open long
    assert e2 == "open" and s2["position"] == 1 and c2 is None


def test_transition_nan_z_holds_position():
    st = {
        **pt._empty_state(),
        "position": 1,
        "entry_es": 5000.0,
        "entry_nq": 18000.0,
        "entry_time": "t0",
        "entry_z": -2.5,
    }
    ns, ev, closed = pt.decide_transition(st, float("nan"), 5010.0, 18010.0, "t1", P)
    assert ev == "in_position" and ns["position"] == 1 and closed is None


# --- close_trade P&L + cost ------------------------------------------------


def test_close_trade_long_spread_pnl_sign_and_cost():
    # long spread (+1): profits when ES outperforms NQ since entry.
    st = {
        "position": 1,
        "entry_es": 5000.0,
        "entry_nq": 18000.0,
        "entry_time": "t0",
        "entry_z": -2.5,
    }
    es, nq = 5050.0, 18000.0  # ES +1%, NQ flat -> spread up -> long-spread wins
    c = pt.close_trade(st, es, nq, 0.3, "t1", cost_bps_per_leg=2.0, notional=20000.0)
    gross = math.log(es / 5000.0) - math.log(nq / 18000.0)
    net = gross - 4.0 * (2.0 / 1e4)  # 4 leg-turns round trip
    assert abs(c["ret"] - round(net, 6)) < 1e-9
    assert abs(c["pnl"] - round(net * 20000.0, 2)) < 1e-6
    assert c["pnl"] > 0
    assert c["direction"] == "long_spread"


def test_close_trade_short_spread_inverts_sign():
    st = {
        "position": -1,
        "entry_es": 5000.0,
        "entry_nq": 18000.0,
        "entry_time": "t0",
        "entry_z": 2.5,
    }
    es, nq = 5050.0, 18000.0  # spread up -> SHORT spread loses
    c = pt.close_trade(st, es, nq, 0.3, "t1", cost_bps_per_leg=2.0, notional=20000.0)
    assert c["pnl"] < 0 and c["direction"] == "short_spread"


def test_close_trade_zero_cost_is_pure_spread_return():
    st = {
        "position": 1,
        "entry_es": 5000.0,
        "entry_nq": 18000.0,
        "entry_time": "t0",
        "entry_z": -2.5,
    }
    c = pt.close_trade(st, 5000.0, 18000.0, 0.0, "t1", cost_bps_per_leg=0.0, notional=20000.0)
    assert c["ret"] == 0.0 and c["pnl"] == 0.0  # no move, no cost


def test_closed_trade_is_build_windows_shaped():
    # forward_test.build_windows needs exit_time + pnl; ensure they're present + typed.
    st = {
        "position": 1,
        "entry_es": 5000.0,
        "entry_nq": 18000.0,
        "entry_time": "t0",
        "entry_z": -2.5,
    }
    c = pt.close_trade(st, 5050.0, 18000.0, 0.3, "2026-07-01T12:00:00Z", 2.0, 20000.0)
    assert isinstance(c["exit_time"], str) and isinstance(c["pnl"], float)


# --- align_latest ----------------------------------------------------------


def _bars(ts_closes):
    return [{"timestamp": t, "close": c} for t, c in ts_closes]


def test_align_latest_basic():
    # zero-padded so string sort == chronological (real ISO timestamps sort this way).
    a = _bars([(f"t{i:03d}", 5000.0 + i) for i in range(45)])
    b = _bars([(f"t{i:03d}", 18000.0 + i) for i in range(45)])
    out = pt.align_latest(a, b, window=40)
    assert out is not None
    ts, ca, cb, z = out
    assert ts == "t044" and ca == 5044.0 and cb == 18044.0
    assert isinstance(z, float) and not math.isnan(z)


def test_align_latest_insufficient_overlap_is_none():
    a = _bars([(f"t{i:03d}", 5000.0 + i) for i in range(30)])
    b = _bars([(f"t{i:03d}", 18000.0 + i) for i in range(30)])
    assert pt.align_latest(a, b, window=40) is None  # <= window aligned bars


def test_align_latest_intersects_timestamps():
    # only t005..t049 overlap; need > window(=10) common bars
    a = _bars([(f"t{i:03d}", 5000.0 + i) for i in range(0, 50)])
    b = _bars([(f"t{i:03d}", 18000.0 + i) for i in range(5, 60)])
    out = pt.align_latest(a, b, window=10)
    assert out is not None
    assert out[0] == "t049"  # latest common timestamp
