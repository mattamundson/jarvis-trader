"""Cost-ledger consistency for the intraday `Backtester`.

Pins the exact structural findings from the 2026-09-17 MES economics audit
(`docs/research/mes-vix-pctile-champion-economics.md` §5) so the state of the
ledger is *measured*, never inferred:

1. `capital` is charged commission at ENTRY (`_process_pending_entry` returns
   `capital_used = _transaction_cost(...)`) and AGAIN at every EXIT
   (`capital_change += pnl - _transaction_cost(...) - _exit_spread_cost(...)`).
   `_transaction_cost` is itself already a round trip (`2 * contracts * cpc`).
   Net: capital pays **4 × contracts × commission_per_contract** per closed
   trade against a true round-trip of `1 × 1.42` (config describes
   COMMISSION_PER_CONTRACT=1.42 as the *round-trip* CME fee).

2. `trade.pnl` carries **no** commission and **no** spread — it is the raw
   price move × contracts × multiplier. So every trade-ledger-derived metric
   (profit_factor, win_rate, engine_sharpe, total_pnl, gross_profit/loss) is
   gross of all costs, while `final_capital`/CAGR/drawdown are net.

These tests are the executable spec for the current behaviour. When the ledger
is fixed, the `test_current_*` cases are *expected to fail* and must be
replaced by the `test_target_*` contract (kept below, marked xfail until then)
in the same PR — so a fix cannot land silently.
"""

from __future__ import annotations

import os

os.environ.setdefault("API_KEY", "local-research-sandbox-dummy-not-a-credential")

import numpy as np
import pandas as pd
import pytest

from backtest.backtester import Backtester

COMM = 1.25  # $/contract — arbitrary; chosen so multiples are unambiguous
MULT = 5.0  # MES multiplier
TICK = 0.25


def _stop_out_fixture() -> pd.DataFrame:
    """1 long entry filled at 100.0, stopped out at 99.0 two bars later."""
    idx = pd.date_range("2024-01-02 09:30", periods=6, freq="5min", tz="UTC")
    px = np.full(6, 100.0)
    df = pd.DataFrame(
        {
            "open": px, "high": px + 0.5, "low": px - 0.5, "close": px,
            "atr": 1.0,
            "entry_signal": "NO_TRADE", "bias": "NEUTRAL",
            "stop_level": np.nan, "target_1": np.nan, "target_2": np.nan, "target_3": np.nan,
            "regime": "TREND",
        },
        index=idx,
    )
    df.loc[idx[1], ["entry_signal", "bias", "stop_level", "target_1", "target_2", "target_3"]] = [
        "ENTRY_NOW", "BULL", 99.0, 101.5, 103.0, 104.0,
    ]
    df.loc[idx[3], "low"] = 98.0
    return df


def _run(spread_ticks: float = 0.0, contracts: int = 1):
    bt = Backtester(
        initial_capital=10_000.0,
        commission_per_contract=COMM,
        slippage_ticks=0.0,
        spread_ticks=spread_ticks,
        fixed_contracts=contracts,
        eod_close=False,
        use_targets=True,
    )
    return bt.run(_stop_out_fixture(), symbol="MES", multiplier=MULT)


# --------------------------------------------------------------------------- #
# Current behaviour (pinned)
# --------------------------------------------------------------------------- #

def test_current_trade_pnl_is_gross_of_all_costs():
    res = _run(spread_ticks=1.0)
    (t,) = res.trades
    # raw move: 1 contract * (99 - 100) * 5 = -5.0 — no commission, no spread
    assert t.pnl == pytest.approx(-1.0 * MULT * 1)


def test_current_capital_pays_commission_four_times_per_contract():
    res = _run(spread_ticks=0.0)
    (t,) = res.trades
    equity_change = res.final_capital - res.initial_capital
    price_move = t.pnl
    commission_paid = price_move - equity_change  # only cost enabled
    # entry: 2*c*COMM ; exit: 2*c*COMM  →  4*c*COMM
    assert commission_paid == pytest.approx(4 * t.contracts * COMM)


@pytest.mark.parametrize("contracts", [1, 3])
def test_current_ledger_equity_gap_equals_two_round_trips(contracts):
    res = _run(spread_ticks=0.0, contracts=contracts)
    gap = res.total_pnl - (res.final_capital - res.initial_capital)
    one_round_trip = 2 * contracts * COMM
    assert gap == pytest.approx(2 * one_round_trip)


def test_current_trade_pnl_carries_no_spread_on_either_side():
    """Spread is invisible to trade.pnl on BOTH sides.

    Entry-side half-spread worsens the fill price (100.00 -> 100.25), but the stop and
    targets are then recomputed from that fill (stop 99.00 -> 99.25), so an ATR-defined
    stop-out loses exactly the same price distance whether or not spread is on. Exit-side
    half-spread is an explicit deduction from `capital` only. Net: `trade.pnl` is
    spread-invariant; `capital` pays 2 * half_spread per closed trade.
    """
    no_spread = _run(spread_ticks=0.0)
    spread = _run(spread_ticks=1.0)
    (t0,), (t1,) = no_spread.trades, spread.trades
    # fills moved by exactly one half-spread each...
    assert t1.entry_price - t0.entry_price == pytest.approx(TICK)
    assert t1.exit_price - t0.exit_price == pytest.approx(TICK)
    # ...but the ledger does not see it
    assert t1.pnl == pytest.approx(t0.pnl)
    # capital pays only the exit-side half-spread beyond price move on THIS fixture:
    # entry-side spread shifted the fill AND the ATR-anchored stop by the same +TICK, so
    # the realised price distance is unchanged; only the explicit exit deduction remains.
    exit_side = TICK * 1.0 * MULT * t1.contracts
    assert (no_spread.final_capital - spread.final_capital) == pytest.approx(exit_side)
    # run-level reporting field counts BOTH sides regardless — a second inconsistency:
    # spread_cost_total overstates realised spread cost when stops are ATR-anchored.
    assert spread.spread_cost_total == pytest.approx(2 * exit_side)


# --------------------------------------------------------------------------- #
# Target contract — flips on when the ledger is fixed
# --------------------------------------------------------------------------- #

@pytest.mark.xfail(strict=True, reason="ledger fix not yet applied; see economics report §5")
def test_target_trade_pnl_reconciles_to_equity():
    res = _run(spread_ticks=1.0, contracts=2)
    assert res.total_pnl == pytest.approx(res.final_capital - res.initial_capital, abs=1e-6)


@pytest.mark.xfail(strict=True, reason="ledger fix not yet applied; see economics report §5")
def test_target_capital_pays_exactly_one_round_trip_commission():
    res = _run(spread_ticks=0.0, contracts=1)
    (t,) = res.trades
    price_move = -1.0 * MULT * t.contracts
    commission_paid = price_move - (res.final_capital - res.initial_capital)
    assert commission_paid == pytest.approx(1 * t.contracts * COMM)
