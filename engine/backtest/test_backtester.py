"""
JARVIS TRADER — Backtester Unit Tests
Verifies 5 critical bug fixes with synthetic data and known outcomes.

Run:  cd engine && .venv/Scripts/python backtest/test_backtester.py
"""
from __future__ import annotations
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Ensure engine/ is on the path so we can import the backtester
sys.path.insert(0, ".")
from backtest.backtester import Backtester, Trade, BacktestResult


# ── Helper ──────────────────────────────────────────────────────────────────

def make_synthetic_df(
    prices: list,
    signals: list,
    dates: list,
    atr_val: float = 1.0,
    highs: list | None = None,
    lows: list | None = None,
    opens: list | None = None,
) -> pd.DataFrame:
    """Create a minimal DataFrame for backtester testing.

    Parameters
    ----------
    prices : list   close prices
    signals : list  entry_signal per bar ('ENTRY_NOW' or 'NO_TRADE')
    dates : list    datetime objects for index
    atr_val : float constant ATR value
    highs / lows / opens : optional overrides (default: close +/- 0.5*ATR)
    """
    n = len(prices)
    df = pd.DataFrame(
        {
            "open": opens if opens else prices,
            "high": highs if highs else [p + 0.5 * atr_val for p in prices],
            "low": lows if lows else [p - 0.5 * atr_val for p in prices],
            "close": prices,
            "volume": [1000] * n,
            "entry_signal": signals,
            "bias": [
                "STRONG_BULL" if s == "ENTRY_NOW" else "NEUTRAL" for s in signals
            ],
            "stop_level": [p - atr_val for p in prices],
            "target_1": [p + 1.5 * atr_val for p in prices],
            "target_2": [p + 2.618 * atr_val for p in prices],
            "target_3": [p + 4.0 * atr_val for p in prices],
            "regime": ["TRENDING_BULL"] * n,
            "atr": [atr_val] * n,
        },
        index=pd.DatetimeIndex(dates),
    )
    df["timestamp"] = df.index
    return df


# ── Test 1: Stop loss exits ALL contracts ───────────────────────────────────

def test_stop_exits_all_contracts():
    """Signal on bar 0, entry on bar 1, price drops below stop on bar 3.
    All 3 tiers of contracts must exit at the stop — none left orphaned."""

    label = "Test 1 — Stop exits all contracts"
    atr = 2.0
    entry_close = 100.0  # signal bar close
    # Bar 1 open = entry price (where fill happens)
    entry_open = 100.0

    # The backtester computes stop_atr_mult from the signal bar:
    #   signal_price = close = 100, stop_level = close - atr = 98
    #   stop_dist = |100 - 98| = 2, stop_atr_mult = 2 / 2 = 1.0
    # Then recalculated at entry: stop = entry_open - 1.0 * atr = 100 - 2 = 98.0
    stop_price = entry_open - 1.0 * atr  # = 98.0

    # Bars: signal, entry, hold, stop-hit, extra
    closes = [entry_close, 100.5, 100.2, 97.0, 97.5]
    opens  = [entry_close, entry_open, 100.3, 99.8, 97.2]
    highs  = [101.0, 101.0, 100.8, 100.0, 98.0]
    lows   = [99.5, 99.5, 99.8, 96.5, 97.0]  # bar 3 low=96.5 < stop=98.0
    signals = ["ENTRY_NOW", "NO_TRADE", "NO_TRADE", "NO_TRADE", "NO_TRADE"]
    dates = [datetime(2025, 1, 6, 10, 0) + timedelta(hours=i) for i in range(5)]

    df = make_synthetic_df(
        prices=closes, signals=signals, dates=dates,
        atr_val=atr, highs=highs, lows=lows, opens=opens,
    )

    bt = Backtester(
        initial_capital=100_000,
        risk_per_trade=0.01,
        commission_per_contract=0.0,
        slippage_ticks=0,
    )
    result = bt.run(df, symbol="SPY", multiplier=1.0)

    # Expectations
    passed = True
    details = []

    if result.total_trades != 1:
        passed = False
        details.append(f"Expected 1 trade, got {result.total_trades}")

    if result.total_trades >= 1:
        trade = result.trades[0]
        if trade.exit_reason != "stop":
            passed = False
            details.append(f"Expected exit_reason='stop', got '{trade.exit_reason}'")

        # All contracts should have exited (negative PnL since stop < entry)
        if trade.pnl >= 0:
            passed = False
            details.append(f"Expected negative PnL (stop loss), got {trade.pnl:.2f}")

        # Verify ALL contract tiers exited: contracts * (stop - entry) * mult
        expected_pnl = trade.contracts * (stop_price - entry_open) * 1.0
        if abs(trade.pnl - expected_pnl) > 0.01:
            passed = False
            details.append(
                f"PnL mismatch: got {trade.pnl:.2f}, "
                f"expected {expected_pnl:.2f} "
                f"({trade.contracts} contracts x {stop_price - entry_open:.2f})"
            )

    status = "PASS" if passed else "FAIL"
    pnl_str = f"PnL: ${result.trades[0].pnl:.2f}" if result.trades else "no trades"
    contracts_str = f"{result.trades[0].contracts} contracts" if result.trades else ""
    reason_str = f"reason: {result.trades[0].exit_reason}" if result.trades else ""
    print(f"{label}... {status} ({pnl_str}, {contracts_str}, {reason_str})")
    if not passed:
        for d in details:
            print(f"   DETAIL: {d}")
    return passed


# ── Test 2: EOD exit at day boundary (not last bar) ────────────────────────

def test_eod_exit_at_day_boundary():
    """Entry on day 1, no targets hit. Position must close at end of day 1
    (bar 6), NOT hold until bar 12 (last bar of day 2)."""

    label = "Test 2 — EOD at day boundary"
    atr = 2.0

    # Day 1: 6 bars (10:00–15:00), Day 2: 6 bars (10:00–15:00)
    day1_base = datetime(2025, 1, 6, 10, 0)
    day2_base = datetime(2025, 1, 7, 10, 0)
    dates = [day1_base + timedelta(hours=i) for i in range(6)] + \
            [day2_base + timedelta(hours=i) for i in range(6)]

    # Flat prices — no targets hit, no stop hit
    closes = [100.0] * 12
    opens  = [100.0] * 12
    highs  = [100.5] * 12
    lows   = [99.5] * 12

    signals = ["ENTRY_NOW"] + ["NO_TRADE"] * 11

    df = make_synthetic_df(
        prices=closes, signals=signals, dates=dates,
        atr_val=atr, highs=highs, lows=lows, opens=opens,
    )

    bt = Backtester(
        initial_capital=100_000,
        risk_per_trade=0.01,
        commission_per_contract=0.0,
        slippage_ticks=0,
    )
    result = bt.run(df, symbol="SPY", multiplier=1.0)

    passed = True
    details = []

    if result.total_trades < 1:
        passed = False
        details.append("No trades were generated")
    else:
        trade = result.trades[0]
        exit_date = trade.exit_date

        # Should exit on day 1's LAST bar (index 5 → 15:00 on Jan 6)
        day1_last = dates[5]  # 2025-01-06 15:00
        day2_last = dates[11]  # 2025-01-07 15:00

        if trade.exit_reason != "eod":
            passed = False
            details.append(f"Expected exit_reason='eod', got '{trade.exit_reason}'")

        if exit_date is not None and hasattr(exit_date, 'date'):
            if exit_date.date() != day1_base.date():
                passed = False
                details.append(
                    f"Exit on {exit_date} but expected day 1 ({day1_base.date()})"
                )
            # Must be bar 6 (index 5), not bar 12 (index 11)
            exit_bar = dates.index(exit_date) + 1 if exit_date in dates else "?"
        else:
            exit_bar = "?"

        if result.total_trades > 1:
            details.append(f"Got {result.total_trades} trades, expected 1")

    status = "PASS" if passed else "FAIL"
    exit_bar_display = exit_bar if result.total_trades >= 1 else "N/A"
    reason = result.trades[0].exit_reason if result.total_trades >= 1 else "N/A"
    print(f"{label}... {status} (exit bar {exit_bar_display}, not bar 12, reason: {reason})")
    if not passed:
        for d in details:
            print(f"   DETAIL: {d}")
    return passed


# ── Test 3: Look-ahead bias — entry at NEXT bar open ───────────────────────

def test_entry_at_next_bar_open():
    """Signal fires on bar 2 (close=100.00). Bar 3 opens at 101.50.
    Entry price MUST be 101.50 (next bar's open), NOT 100.00."""

    label = "Test 3 — Entry at next bar open"
    atr = 2.0

    closes  = [99.0, 99.5, 100.0, 102.0, 103.0]
    opens   = [98.5, 99.0, 99.5, 101.5, 102.0]
    highs   = [99.5, 100.0, 100.5, 103.0, 104.0]
    lows    = [98.0, 98.5, 99.0, 101.0, 101.5]
    signals = ["NO_TRADE", "NO_TRADE", "ENTRY_NOW", "NO_TRADE", "NO_TRADE"]
    dates = [datetime(2025, 1, 6, 10, 0) + timedelta(hours=i) for i in range(5)]

    df = make_synthetic_df(
        prices=closes, signals=signals, dates=dates,
        atr_val=atr, highs=highs, lows=lows, opens=opens,
    )

    bt = Backtester(
        initial_capital=100_000,
        risk_per_trade=0.01,
        commission_per_contract=0.0,
        slippage_ticks=0,
    )
    result = bt.run(df, symbol="SPY", multiplier=1.0)

    passed = True
    details = []

    if result.total_trades < 1:
        passed = False
        details.append("No trades generated")
    else:
        trade = result.trades[0]
        expected_entry = 101.50  # bar 3's open

        if abs(trade.entry_price - expected_entry) > 0.01:
            passed = False
            details.append(
                f"Entry price = {trade.entry_price:.2f}, "
                f"expected {expected_entry:.2f} (bar 3 open)"
            )

        # Stop/target should be calculated from 101.50, not 100.00
        # Signal bar: close=100, stop_level=100-2=98, stop_dist=2, atr=2
        # stop_atr_mult = 2/2 = 1.0. Recalculated: stop = 101.5 - 1.0*2 = 99.5
        expected_stop = expected_entry - 1.0 * atr  # = 99.50
        if abs(trade.stop_price - expected_stop) > 0.05:
            passed = False
            details.append(
                f"Stop = {trade.stop_price:.2f}, "
                f"expected ~{expected_stop:.2f} (from entry {expected_entry})"
            )

    status = "PASS" if passed else "FAIL"
    entry_str = f"entry={result.trades[0].entry_price:.2f}" if result.trades else "no trade"
    print(f"{label}... {status} ({entry_str}, expected 101.50)")
    if not passed:
        for d in details:
            print(f"   DETAIL: {d}")
    return passed


# ── Test 4: Commission and slippage deducted ────────────────────────────────

def test_commission_slippage_deducted():
    """Trade with commission and slippage. Verify transaction costs are deducted
    at both entry and exit. Uses standard exit ratios so trade closes via EOD."""

    label = "Test 4 — Commission/slippage deducted"
    atr = 2.0
    initial_capital = 100_000.0
    commission = 2.50
    slippage = 1
    tick_size = 0.01  # SPY is an ETF -> tick_size = 0.01

    entry_close = 100.0
    entry_open = 100.0

    # Signal bar: close=100, stop_level=98 (100-2), T1=103 (100+1.5*2)
    # stop_atr_mult = 2/2 = 1.0
    # Recalculated at entry: stop = 100 - 1.0*2 = 98, T1 = 100 + 1.5*2 = 103

    # 2-day setup: Day 1 has signal+entry+T1 hit, T3 contracts close at EOD
    day1 = datetime(2025, 1, 6, 10, 0)
    day2 = datetime(2025, 1, 7, 10, 0)
    dates = [day1 + timedelta(hours=i) for i in range(6)] + \
            [day2 + timedelta(hours=i) for i in range(6)]

    # Day 1: signal bar 0, entry bar 1, T1 hit bar 3, EOD closes remaining
    closes  = [100.0, 100.5, 101.0, 103.5, 103.0, 102.5,
               102.0, 102.0, 102.0, 102.0, 102.0, 102.0]
    opens   = [100.0, 100.0, 100.3, 101.0, 103.0, 103.0,
               102.0, 102.0, 102.0, 102.0, 102.0, 102.0]
    highs   = [100.5, 101.0, 101.5, 104.0, 103.5, 103.0,
               102.5, 102.5, 102.5, 102.5, 102.5, 102.5]
    lows    = [99.5, 99.5, 100.0, 100.5, 102.5, 102.0,
               101.5, 101.5, 101.5, 101.5, 101.5, 101.5]
    signals = ["ENTRY_NOW"] + ["NO_TRADE"] * 11

    df = make_synthetic_df(
        prices=closes, signals=signals, dates=dates,
        atr_val=atr, highs=highs, lows=lows, opens=opens,
    )

    # First run WITHOUT commission to get the zero-cost baseline
    bt_no_cost = Backtester(
        initial_capital=initial_capital,
        risk_per_trade=0.01,
        commission_per_contract=0.0,
        slippage_ticks=0,
    )
    result_no_cost = bt_no_cost.run(df.copy(), symbol="SPY", multiplier=1.0)

    # Then run WITH commission
    bt = Backtester(
        initial_capital=initial_capital,
        risk_per_trade=0.01,
        commission_per_contract=commission,
        slippage_ticks=slippage,
    )
    result = bt.run(df.copy(), symbol="SPY", multiplier=1.0)

    passed = True
    details = []

    if result.total_trades < 1:
        passed = False
        details.append("No trades generated")
    elif result_no_cost.total_trades < 1:
        passed = False
        details.append("No trades generated in baseline (no-cost) run")
    else:
        trade = result.trades[0]
        n = trade.contracts

        # The difference in final capital should equal total transaction costs
        cost_per = commission + slippage * tick_size
        # Entry: n contracts cost. Exits: T1 contracts + EOD remaining contracts
        # Total exit contracts = n (all eventually exit). So total events = 2n.
        total_expected_cost = 2 * n * cost_per

        actual_cost = result_no_cost.final_capital - result.final_capital

        if abs(actual_cost - total_expected_cost) > 0.02:
            passed = False
            details.append(
                f"Cost difference = {actual_cost:.2f}, "
                f"expected {total_expected_cost:.2f} "
                f"(2 x {n} contracts x {cost_per:.4f})"
            )

        if actual_cost <= 0:
            passed = False
            details.append(
                f"Commission run should have LESS capital, "
                f"but diff={actual_cost:.2f}"
            )

    status = "PASS" if passed else "FAIL"
    if result.trades:
        t = result.trades[0]
        n = t.contracts
        cost_per = commission + slippage * tick_size
        actual_cost = result_no_cost.final_capital - result.final_capital
        print(
            f"{label}... {status} "
            f"({n} contracts, deducted=${actual_cost:.2f}, "
            f"final=${result.final_capital:.2f})"
        )
    else:
        print(f"{label}... {status} (no trades)")
    if not passed:
        for d in details:
            print(f"   DETAIL: {d}")
    return passed


# ── Test 5: Sharpe ratio uses daily equity curve ────────────────────────────

def test_sharpe_uses_daily_returns():
    """Verify Sharpe = mean(daily_returns) / std(daily_returns) * sqrt(252),
    computed from the equity curve, not from raw trade P&L."""

    label = "Test 5 — Sharpe uses daily returns"

    # Create a multi-day scenario with a couple of trades so the equity
    # curve has enough variation to compute Sharpe.
    atr = 2.0
    dates = []
    closes = []
    opens = []
    highs = []
    lows = []
    signals = []

    # Day 1: 6 bars, signal on bar 0 -> entry bar 1, T1 hit on bar 3
    day1 = datetime(2025, 1, 6, 10, 0)
    for i in range(6):
        dates.append(day1 + timedelta(hours=i))
    closes  += [100.0, 100.5, 101.0, 103.5, 103.0, 102.5]
    opens   += [100.0, 100.0, 100.3, 101.0, 103.0, 103.0]
    highs   += [100.5, 101.0, 101.5, 104.0, 103.5, 103.0]
    lows    += [99.5, 99.5, 100.0, 100.5, 102.5, 102.0]
    signals += ["ENTRY_NOW", "NO_TRADE", "NO_TRADE", "NO_TRADE", "NO_TRADE", "NO_TRADE"]

    # Day 2: 6 bars, signal on bar 0 -> entry bar 1, stop hit bar 3
    day2 = datetime(2025, 1, 7, 10, 0)
    for i in range(6):
        dates.append(day2 + timedelta(hours=i))
    closes  += [102.0, 102.5, 101.5, 97.0, 97.5, 98.0]
    opens   += [102.0, 102.0, 102.3, 101.0, 97.0, 97.5]
    highs   += [102.5, 103.0, 102.8, 101.5, 98.0, 98.5]
    lows    += [101.5, 101.5, 101.0, 96.5, 96.5, 97.0]
    signals += ["ENTRY_NOW", "NO_TRADE", "NO_TRADE", "NO_TRADE", "NO_TRADE", "NO_TRADE"]

    # Day 3: 6 bars, no trades (let equity sit flat for diversity)
    day3 = datetime(2025, 1, 8, 10, 0)
    for i in range(6):
        dates.append(day3 + timedelta(hours=i))
    closes  += [98.0] * 6
    opens   += [98.0] * 6
    highs   += [98.5] * 6
    lows    += [97.5] * 6
    signals += ["NO_TRADE"] * 6

    df = make_synthetic_df(
        prices=closes, signals=signals, dates=dates,
        atr_val=atr, highs=highs, lows=lows, opens=opens,
    )

    bt = Backtester(
        initial_capital=100_000,
        risk_per_trade=0.01,
        commission_per_contract=0.0,
        slippage_ticks=0,
    )
    result = bt.run(df, symbol="SPY", multiplier=1.0)

    passed = True
    details = []

    # Recompute Sharpe from equity curve independently
    equity = np.array(result.equity_curve)
    if len(equity) > 2:
        daily_returns = np.diff(equity) / equity[:-1]
        daily_returns = daily_returns[~np.isnan(daily_returns)]
        if len(daily_returns) > 1 and daily_returns.std() > 0:
            expected_sharpe = float(
                (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
            )
        else:
            expected_sharpe = 0.0
    else:
        expected_sharpe = 0.0

    if abs(result.sharpe_ratio - expected_sharpe) > 0.01:
        passed = False
        details.append(
            f"Sharpe = {result.sharpe_ratio:.4f}, "
            f"expected {expected_sharpe:.4f} from equity curve"
        )

    # Sharpe should NOT be zero if there were trades with P&L variation
    if result.total_trades > 0 and result.sharpe_ratio == 0.0 and expected_sharpe != 0.0:
        passed = False
        details.append("Sharpe is 0 despite having trades with varied P&L")

    status = "PASS" if passed else "FAIL"
    print(
        f"{label}... {status} "
        f"(sharpe={result.sharpe_ratio:.4f}, "
        f"trades={result.total_trades}, "
        f"equity points={len(result.equity_curve)})"
    )
    if not passed:
        for d in details:
            print(f"   DETAIL: {d}")
    return passed


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("JARVIS TRADER — Backtester Regression Tests")
    print("=" * 60)
    print()

    results = [
        test_stop_exits_all_contracts(),
        test_eod_exit_at_day_boundary(),
        test_entry_at_next_bar_open(),
        test_commission_slippage_deducted(),
        test_sharpe_uses_daily_returns(),
    ]

    print()
    passed = sum(results)
    total = len(results)
    if all(results):
        print(f"ALL {total} TESTS PASSED")
    else:
        failed = total - passed
        print(f"{passed}/{total} passed, {failed} FAILED")
        sys.exit(1)
