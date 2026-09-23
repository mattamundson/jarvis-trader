"""Cost-ledger contract for the intraday `Backtester` — post-fix (reading A).

History: the pre-fix version pinned five *current-behaviour* cases documenting a defect — `capital`
was charged commission at entry AND at every exit (`_transaction_cost` itself being a round trip, so
4× per contract), while `trade.pnl` carried no commission and no spread at all. That made the
trade-ledger metrics (PF, win rate, engine Sharpe, `total_pnl`) optimistic and the equity-curve
metrics (CAGR, drawdown) pessimistic, simultaneously. Those pins were deleted with the fix, as
designed, so the defect cannot quietly return.

Decided 2026-09-18: `COMMISSION_PER_CONTRACT` (1.42) is the **round trip** (reading A). A contract is
charged it once. Costs are attributed to trades at the end of `run()`, proportionally to contracts —
costs are charged per contract, so the allocation is faithful and reconciliation is exact by
construction rather than by four matching exit-path edits.
"""

from __future__ import annotations

import os

os.environ.setdefault("API_KEY", "local-research-sandbox-dummy-not-a-credential")

import numpy as np
import pandas as pd
import pytest

from backtest.backtester import Backtester

COMM = 1.25  # $/contract round trip — arbitrary, chosen so multiples are unambiguous
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


def _run(spread_ticks: float = 0.0, contracts: int = 1, commission: float = COMM):
    bt = Backtester(
        initial_capital=10_000.0,
        commission_per_contract=commission,
        slippage_ticks=0.0,
        spread_ticks=spread_ticks,
        fixed_contracts=contracts,
        eod_close=False,
        use_targets=True,
    )
    return bt.run(_stop_out_fixture(), symbol="MES", multiplier=MULT)


# --------------------------------------------------------------------------- #
# The contract
# --------------------------------------------------------------------------- #

def test_ledger_reconciles_to_equity():
    """The whole point: sum(trade.pnl) must equal final_capital - initial_capital."""
    for spread in (0.0, 1.0):
        for contracts in (1, 3):
            res = _run(spread_ticks=spread, contracts=contracts)
            assert res.total_pnl == pytest.approx(
                res.final_capital - res.initial_capital, abs=1e-6
            ), f"ledger != equity at spread={spread} contracts={contracts}"


def test_capital_pays_exactly_one_round_trip_per_contract():
    """Reading A: COMM is the round trip, charged ONCE per contract."""
    for contracts in (1, 2, 3):
        res = _run(spread_ticks=0.0, contracts=contracts)
        (t,) = res.trades
        raw_move = -1.0 * MULT * contracts
        commission_paid = raw_move - (res.final_capital - res.initial_capital)
        assert commission_paid == pytest.approx(contracts * COMM), (
            f"expected {contracts}x{COMM} once, got {commission_paid}"
        )
        assert t.contracts == contracts


def test_trade_pnl_is_net_of_cost():
    """Trade-ledger metrics must not be cost-free any more."""
    res = _run(spread_ticks=1.0, contracts=2)
    (t,) = res.trades
    raw_move = -1.0 * MULT * 2
    assert t.pnl < raw_move, "pnl should include cost, not be the raw price move"
    assert t.pnl == pytest.approx(res.final_capital - res.initial_capital, abs=1e-6)


def test_spread_cost_total_equals_what_was_charged():
    no_spread = _run(spread_ticks=0.0)
    spread = _run(spread_ticks=1.0)
    charged = no_spread.final_capital - spread.final_capital
    assert spread.spread_cost_total == pytest.approx(charged), (
        f"reported {spread.spread_cost_total} vs charged {charged}"
    )


def test_entry_side_spread_cancels_in_realised_distance():
    """Entry half-spread shifts the fill AND the ATR-anchored stop, so the distance is unchanged."""
    no_spread = _run(spread_ticks=0.0)
    spread = _run(spread_ticks=1.0)
    (t0,), (t1,) = no_spread.trades, spread.trades
    assert t1.entry_price - t0.entry_price == pytest.approx(TICK)
    assert t1.exit_price - t0.exit_price == pytest.approx(TICK)
    # The realised distance is identical and BOTH runs pay the same commission, so the only
    # difference in net pnl is the exit-side spread. (A first version of this assertion also added
    # COMM; the revert-on-failure guard caught it before it shipped.)
    assert (t0.pnl - t1.pnl) == pytest.approx(TICK * MULT)


def test_commission_disabled_means_no_commission_charge():
    res = _run(spread_ticks=0.0, contracts=1, commission=0.0)
    (t,) = res.trades
    assert t.pnl == pytest.approx(-1.0 * MULT)
    assert res.final_capital - res.initial_capital == pytest.approx(t.pnl)


def test_commission_scales_linearly_with_rate():
    cheap = _run(spread_ticks=0.0, contracts=2, commission=0.5)
    dear = _run(spread_ticks=0.0, contracts=2, commission=2.0)
    delta = cheap.final_capital - dear.final_capital
    assert delta == pytest.approx(2 * (2.0 - 0.5))
