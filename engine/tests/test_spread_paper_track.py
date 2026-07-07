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


# --- multi-pair generalization ---------------------------------------------


def test_pair_registry_es_nq_keeps_root_ledger():
    # ES-NQ must stay at subdir="" so the LIVE forward record is undisturbed by the
    # multi-pair refactor; MES-M2K gets an isolated subdir.
    assert pt.PAIR_REGISTRY["ES-NQ"]["subdir"] == ""
    assert pt.PAIR_REGISTRY["ES-NQ"]["lineage"] == pt.LINEAGE
    assert pt.PAIR_REGISTRY["ES-NQ"]["symbol"] == pt.SPREAD_SYMBOL
    assert pt.PAIR_REGISTRY["MES-M2K"]["subdir"] == "MES-M2K"
    assert pt.PAIR_REGISTRY["MES-M2K"]["lineage"] != pt.LINEAGE


def test_close_trade_honors_pair_symbol_and_lineage():
    st = {
        "position": 1,
        "entry_es": 5000.0,
        "entry_nq": 2000.0,
        "entry_time": "t0",
        "entry_z": -2.5,
    }
    c = pt.close_trade(
        st,
        5050.0,
        2000.0,
        0.3,
        "t1",
        2.0,
        20000.0,
        pair_symbol="MES_M2K_SPREAD",
        lineage="mes_m2k_spread_v1",
    )
    assert c["symbol"] == "MES_M2K_SPREAD"
    # Nested decision_identity carrying "<lineage>::<composite_symbol>".
    assert (
        c["strategy_params"]["decision_identity"]["lineage"] == "mes_m2k_spread_v1::MES_M2K_SPREAD"
    )


def test_close_trade_defaults_to_es_nq():
    st = {
        "position": 1,
        "entry_es": 5000.0,
        "entry_nq": 18000.0,
        "entry_time": "t0",
        "entry_z": -2.5,
    }
    c = pt.close_trade(st, 5050.0, 18000.0, 0.3, "t1", 2.0, 20000.0)
    assert c["symbol"] == pt.SPREAD_SYMBOL
    assert (
        c["strategy_params"]["decision_identity"]["lineage"] == f"{pt.LINEAGE}::{pt.SPREAD_SYMBOL}"
    )


def test_close_trade_stamp_is_read_by_forward_test_trade_lineage():
    # The whole point of the nested stamp: forward_test must pick the lineage up so
    # the dark record can graduate through the lineage track.
    from backtest import forward_test as ft

    st = {
        "position": 1,
        "entry_es": 5000.0,
        "entry_nq": 2000.0,
        "entry_time": "t0",
        "entry_z": -2.5,
    }
    c = pt.close_trade(
        st,
        5050.0,
        2000.0,
        0.3,
        "2026-07-01T15:00:00Z",
        2.0,
        20000.0,
        pair_symbol="MES_M2K_SPREAD",
        lineage="mes_m2k_spread_v1",
    )
    assert ft.trade_lineage(c) == "mes_m2k_spread_v1::MES_M2K_SPREAD"
    # pnl/symbol unchanged (regression guard on the live ES-NQ math contract)
    assert isinstance(c["pnl"], float) and c["symbol"] == "MES_M2K_SPREAD"


def test_decide_transition_threads_pair_identity_into_closed_trade():
    st = {
        **pt._empty_state(),
        "position": -1,
        "entry_es": 5000.0,
        "entry_nq": 2000.0,
        "entry_time": "t0",
        "entry_z": 2.5,
    }
    _, ev, closed = pt.decide_transition(
        st,
        0.3,
        5010.0,
        2010.0,
        "t1",
        P,
        pair_symbol="MES_M2K_SPREAD",
        lineage="mes_m2k_spread_v1",
    )
    assert ev == "close"
    assert closed["symbol"] == "MES_M2K_SPREAD"
    assert (
        closed["strategy_params"]["decision_identity"]["lineage"]
        == "mes_m2k_spread_v1::MES_M2K_SPREAD"
    )


def test_track_dir_and_ledgers_isolate_per_pair(tmp_path):
    root = pt._track_dir(tmp_path, "")  # ES-NQ legacy root
    sub = pt._track_dir(tmp_path, "MES-M2K")
    assert root != sub
    assert sub.parent == root  # subdir nested under the spread_paper_track root

    # writing to one ledger must not leak into the other
    pt._append_jsonl(root / "closed_trades.jsonl", {"exit_time": "t1", "pnl": 1.0})
    pt._append_jsonl(sub / "closed_trades.jsonl", {"exit_time": "t1", "pnl": 2.0})
    es_nq = pt.load_closed_trades(tmp_path, "")
    mes_m2k = pt.load_closed_trades(tmp_path, "MES-M2K")
    assert len(es_nq) == 1 and es_nq[0]["pnl"] == 1.0
    assert len(mes_m2k) == 1 and mes_m2k[0]["pnl"] == 2.0
