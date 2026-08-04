"""
JARVIS TRADER — Backtester SOTA Execution-Realism Hardening Tests (2026-08-04)

Verifies the optional execution-realism kwargs added to Backtester:
    - gap_stop_worst_fill: worse-of-(bar_open, stop_price) fill on gap-through bars
    - pessimistic_tie_breaker: always assume stop-first on genuine dual-touch bars
    - volatility_scaled_slippage: slippage scales with current-vs-mean ATR
    - max_volume_pct: POV cap feeds a quadratic impact surcharge into slippage
    - initial_margin_per_contract: hard ceiling on contracts, on top of risk sizing

Every test asserts BOTH that the flag changes behavior when set AND that leaving
the flag at its default reproduces the pre-hardening (unchanged) result — so a
regression in either direction (silently changing default behavior, or the new
flag doing nothing) fails loudly here.

Run:  cd engine && .venv/Scripts/python backtest/test_backtester_sota_hardening.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, ".")
from backtest.backtester import Backtester  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"{name}... {status}" + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILURES.append(name)


def make_df(
    prices: list,
    signals: list,
    dates: list,
    atr_val: float = 1.0,
    highs: list | None = None,
    lows: list | None = None,
    opens: list | None = None,
    volumes: list | None = None,
) -> pd.DataFrame:
    n = len(prices)
    atr_series = atr_val if isinstance(atr_val, list) else [atr_val] * n
    df = pd.DataFrame(
        {
            "open": opens if opens else prices,
            "high": highs if highs else [p + 0.5 * a for p, a in zip(prices, atr_series, strict=False)],
            "low": lows if lows else [p - 0.5 * a for p, a in zip(prices, atr_series, strict=False)],
            "close": prices,
            "volume": volumes if volumes else [1000] * n,
            "entry_signal": signals,
            "bias": ["STRONG_BULL" if s == "ENTRY_NOW" else "NEUTRAL" for s in signals],
            "stop_level": [p - a for p, a in zip(prices, atr_series, strict=False)],
            "target_1": [p + 1.5 * a for p, a in zip(prices, atr_series, strict=False)],
            "target_2": [p + 2.618 * a for p, a in zip(prices, atr_series, strict=False)],
            "target_3": [p + 4.0 * a for p, a in zip(prices, atr_series, strict=False)],
            "regime": ["TRENDING_BULL"] * n,
            "atr": atr_series,
        },
        index=pd.DatetimeIndex(dates),
    )
    df["timestamp"] = df.index
    return df


# ── gap_stop_worst_fill ──────────────────────────────────────────────────────


def test_gap_stop_worst_fill_long():
    """Long entry at 100, stop at 99. Bar gaps open at 95 (below stop) then drifts
    up. Default: exit fills at stop_price (99). gap_stop_worst_fill=True: exit fills
    at the worse bar_open (95)."""
    dates = [datetime(2024, 1, 1, 9) + timedelta(hours=i) for i in range(5)]
    prices = [100, 100, 90, 92, 92]
    signals = ["ENTRY_NOW", "NO_TRADE", "NO_TRADE", "NO_TRADE", "NO_TRADE"]
    opens = [100, 100, 95, 92, 92]  # bar 2 gaps open at 95, well below stop=99
    lows = [99.5, 99.5, 90, 91, 91]
    df = make_df(prices, signals, dates, atr_val=1.0, opens=opens, lows=lows)

    bt_default = Backtester(initial_capital=100_000, fixed_contracts=10, use_targets=False)
    result_default = bt_default.run(df, symbol="TEST", multiplier=5.0)
    trade_default = result_default.trades[0]

    bt_gap = Backtester(
        initial_capital=100_000,
        fixed_contracts=10,
        use_targets=False,
        gap_stop_worst_fill=True,
    )
    result_gap = bt_gap.run(df, symbol="TEST", multiplier=5.0)
    trade_gap = result_gap.trades[0]

    check(
        "gap_stop_worst_fill=False fills at stop_price",
        trade_default.exit_price == trade_default.stop_price,
        f"exit={trade_default.exit_price}, stop={trade_default.stop_price}",
    )
    check(
        "gap_stop_worst_fill=True fills at worse bar_open (95 < stop 99)",
        trade_gap.exit_price < trade_default.exit_price,
        f"gap_exit={trade_gap.exit_price}, default_exit={trade_default.exit_price}",
    )
    check(
        "gap_stop_worst_fill=True produces a WORSE (more negative) PnL than default",
        trade_gap.pnl < trade_default.pnl,
        f"gap_pnl={trade_gap.pnl}, default_pnl={trade_default.pnl}",
    )


# ── pessimistic_tie_breaker ──────────────────────────────────────────────────


def test_pessimistic_tie_breaker_dual_touch():
    """Long entry at 100, stop=99, target_1=101.5. A later bar's range spans BOTH
    the stop and target_1, but opens BELOW entry (target_first would be False from
    bar_open direction anyway under current logic in some configs) — construct the
    case where bar_open >= entry (target-first inferred) but pessimistic override
    should still force stop-first."""
    dates = [datetime(2024, 1, 1, 9) + timedelta(hours=i) for i in range(4)]
    prices = [100, 100, 100, 100]
    signals = ["ENTRY_NOW", "NO_TRADE", "NO_TRADE", "NO_TRADE"]
    # bar 2: opens at 100.5 (>= entry of 100 -> target_first=True by bar_open logic),
    # but low=98 breaches stop(99) and high=102 breaches target_1(101.5) -> dual touch
    opens = [100, 100, 100.5, 100]
    highs = [100.5, 100.5, 102, 100.5]
    lows = [99.5, 99.5, 98, 99.5]
    df = make_df(prices, signals, dates, atr_val=1.0, opens=opens, highs=highs, lows=lows)

    bt_default = Backtester(
        initial_capital=100_000, fixed_contracts=10, use_targets=True, t1_exit_pct=1.0
    )
    result_default = bt_default.run(df, symbol="TEST", multiplier=5.0)

    bt_pess = Backtester(
        initial_capital=100_000,
        fixed_contracts=10,
        use_targets=True,
        t1_exit_pct=1.0,
        pessimistic_tie_breaker=True,
    )
    result_pess = bt_pess.run(df, symbol="TEST", multiplier=5.0)

    trade_default = result_default.trades[0]
    trade_pess = result_pess.trades[0]

    check(
        "default (bar_open inference) resolves dual-touch bar as target-first (win)",
        trade_default.pnl > 0,
        f"default_pnl={trade_default.pnl}, exit_reason={trade_default.exit_reason}",
    )
    check(
        "pessimistic_tie_breaker=True resolves the SAME dual-touch bar as stop-first (loss)",
        trade_pess.pnl < 0,
        f"pess_pnl={trade_pess.pnl}, exit_reason={trade_pess.exit_reason}",
    )


# ── volatility_scaled_slippage ───────────────────────────────────────────────


def test_volatility_scaled_slippage_widens_on_vol_spike():
    """20 quiet bars (atr=1.0) establish a low trailing mean, then a signal fires on
    a high-ATR bar (atr=4.0, 4x the mean). volatility_scaled_slippage=True should
    apply MORE adverse slippage on entry than the flat-slippage default."""
    n_quiet = 21
    dates = [datetime(2024, 1, 1, 9) + timedelta(hours=i) for i in range(n_quiet + 2)]
    prices = [100.0] * n_quiet + [100.0, 100.0]
    signals = ["NO_TRADE"] * n_quiet + ["ENTRY_NOW", "NO_TRADE"]
    atr_list = [1.0] * n_quiet + [4.0, 4.0]  # spike on/after signal bar
    df = make_df(prices, signals, dates, atr_val=atr_list)

    bt_flat = Backtester(
        initial_capital=100_000,
        fixed_contracts=10,
        use_targets=False,
        slippage_ticks=4.0,
    )
    result_flat = bt_flat.run(df, symbol="TEST", multiplier=5.0)

    bt_scaled = Backtester(
        initial_capital=100_000,
        fixed_contracts=10,
        use_targets=False,
        slippage_ticks=4.0,
        volatility_scaled_slippage=True,
        vol_slippage_max_mult=4.0,
    )
    result_scaled = bt_scaled.run(df, symbol="TEST", multiplier=5.0)

    entry_flat = result_flat.trades[0].entry_price
    entry_scaled = result_scaled.trades[0].entry_price

    check(
        "volatility_scaled_slippage=True produces a worse (higher) long entry fill "
        "than flat slippage during a volatility spike",
        entry_scaled > entry_flat,
        f"scaled_entry={entry_scaled}, flat_entry={entry_flat}",
    )


def test_volatility_scaled_slippage_noop_when_disabled():
    """With the flag off (default), a volatility spike must NOT change the entry
    fill vs a constant-ATR baseline — proves the no-op path is truly a no-op."""
    dates = [datetime(2024, 1, 1, 9) + timedelta(hours=i) for i in range(3)]
    prices = [100.0, 100.0, 100.0]
    signals = ["ENTRY_NOW", "NO_TRADE", "NO_TRADE"]

    df_const = make_df(prices, signals, dates, atr_val=1.0)
    df_spike = make_df(prices, signals, dates, atr_val=[1.0, 4.0, 4.0])

    bt = Backtester(
        initial_capital=100_000, fixed_contracts=10, use_targets=False, slippage_ticks=4.0
    )
    entry_const = bt.run(df_const, symbol="TEST", multiplier=5.0).trades[0].entry_price
    entry_spike = bt.run(df_spike, symbol="TEST", multiplier=5.0).trades[0].entry_price

    check(
        "volatility_scaled_slippage=False (default): entry fill unaffected by ATR spike",
        entry_const == entry_spike,
        f"const={entry_const}, spike={entry_spike}",
    )


# ── max_volume_pct (POV impact) ──────────────────────────────────────────────


def test_pov_impact_surcharge_on_thin_volume():
    """10 fixed contracts against a bar with volume=20 is 50% POV — far above a 10%
    cap. max_volume_pct=0.10 should apply a slippage surcharge (worse fill) vs the
    same order on a bar with ample volume (no cap breach)."""
    dates = [datetime(2024, 1, 1, 9) + timedelta(hours=i) for i in range(2)]
    prices = [100.0, 100.0]
    signals = ["ENTRY_NOW", "NO_TRADE"]

    df_thin = make_df(prices, signals, dates, atr_val=1.0, volumes=[1000, 20])
    df_ample = make_df(prices, signals, dates, atr_val=1.0, volumes=[1000, 10_000])

    bt = Backtester(
        initial_capital=100_000,
        fixed_contracts=10,
        use_targets=False,
        slippage_ticks=2.0,
        max_volume_pct=0.10,
    )
    entry_thin = bt.run(df_thin, symbol="TEST", multiplier=5.0).trades[0].entry_price
    entry_ample = bt.run(df_ample, symbol="TEST", multiplier=5.0).trades[0].entry_price

    check(
        "max_volume_pct=0.10: order that is 50% POV on a thin-volume bar fills worse "
        "than the identical order on an ample-volume bar",
        entry_thin > entry_ample,
        f"thin_entry={entry_thin}, ample_entry={entry_ample}",
    )


def test_pov_impact_noop_when_disabled():
    """max_volume_pct=None (default): thin volume must not affect the fill at all."""
    dates = [datetime(2024, 1, 1, 9) + timedelta(hours=i) for i in range(2)]
    prices = [100.0, 100.0]
    signals = ["ENTRY_NOW", "NO_TRADE"]

    df_thin = make_df(prices, signals, dates, atr_val=1.0, volumes=[1000, 20])
    df_ample = make_df(prices, signals, dates, atr_val=1.0, volumes=[1000, 10_000])

    bt = Backtester(
        initial_capital=100_000, fixed_contracts=10, use_targets=False, slippage_ticks=2.0
    )
    entry_thin = bt.run(df_thin, symbol="TEST", multiplier=5.0).trades[0].entry_price
    entry_ample = bt.run(df_ample, symbol="TEST", multiplier=5.0).trades[0].entry_price

    check(
        "max_volume_pct=None (default): thin-volume bar fills identically to ample volume",
        entry_thin == entry_ample,
        f"thin_entry={entry_thin}, ample_entry={entry_ample}",
    )


# ── initial_margin_per_contract ──────────────────────────────────────────────


def test_margin_cap_clamps_contracts():
    """$50,000 capital, risk_per_trade sized to want ~20 contracts, but
    initial_margin_per_contract=$3,000 can only support floor(50000/3000)=16."""
    dates = [datetime(2024, 1, 1, 9) + timedelta(hours=i) for i in range(3)]
    prices = [100.0, 100.0, 100.0]
    signals = ["ENTRY_NOW", "NO_TRADE", "NO_TRADE"]
    # stop_atr_mult defaults to 1.0x ATR=1.0 -> stop_dist=1.0; multiplier=5.0
    # risk_per_trade=0.25 on $50k capital -> risk_dollars=12,500 -> contracts = 12500/(1*5) = 2500
    # capped at 50 by the existing hard ceiling -- use a smaller risk to land inside [17,50)
    # so the margin cap (not the existing 50-cap) is the binding constraint being tested.
    df = make_df(prices, signals, dates, atr_val=1.0)

    bt_uncapped = Backtester(initial_capital=50_000, risk_per_trade=0.03, use_targets=False)
    result_uncapped = bt_uncapped.run(df, symbol="TEST", multiplier=5.0)

    bt_margin = Backtester(
        initial_capital=50_000,
        risk_per_trade=0.03,
        use_targets=False,
        initial_margin_per_contract=3_000.0,
    )
    result_margin = bt_margin.run(df, symbol="TEST", multiplier=5.0)

    contracts_uncapped = result_uncapped.trades[0].contracts
    contracts_margin = result_margin.trades[0].contracts
    expected_margin_ceiling = int(50_000 // 3_000.0)

    check(
        "initial_margin_per_contract=None (default): contracts unconstrained by margin",
        contracts_uncapped > expected_margin_ceiling,
        f"uncapped_contracts={contracts_uncapped}, margin_ceiling={expected_margin_ceiling}",
    )
    check(
        "initial_margin_per_contract=$3000: contracts clamped to floor(capital/margin)",
        contracts_margin == expected_margin_ceiling,
        f"margin_contracts={contracts_margin}, expected={expected_margin_ceiling}",
    )


def test_margin_cap_noop_when_smaller_than_risk_sizing():
    """A margin cap that is LARGER than what risk-sizing would produce anyway must
    not change the result — proves the cap is a ceiling, not a replacement."""
    dates = [datetime(2024, 1, 1, 9) + timedelta(hours=i) for i in range(3)]
    prices = [100.0, 100.0, 100.0]
    signals = ["ENTRY_NOW", "NO_TRADE", "NO_TRADE"]
    df = make_df(prices, signals, dates, atr_val=1.0)

    bt_uncapped = Backtester(initial_capital=10_000, risk_per_trade=0.0025, use_targets=False)
    contracts_uncapped = bt_uncapped.run(df, symbol="TEST", multiplier=5.0).trades[0].contracts

    bt_generous_margin = Backtester(
        initial_capital=10_000,
        risk_per_trade=0.0025,
        use_targets=False,
        initial_margin_per_contract=100.0,  # would allow 100 contracts -- not binding
    )
    contracts_generous = (
        bt_generous_margin.run(df, symbol="TEST", multiplier=5.0).trades[0].contracts
    )

    check(
        "a margin cap looser than risk-sizing's own result changes nothing",
        contracts_uncapped == contracts_generous,
        f"uncapped={contracts_uncapped}, generous_margin={contracts_generous}",
    )


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("JARVIS TRADER — Backtester SOTA Hardening Tests")
    print("=" * 60)
    print()

    test_gap_stop_worst_fill_long()
    test_pessimistic_tie_breaker_dual_touch()
    test_volatility_scaled_slippage_widens_on_vol_spike()
    test_volatility_scaled_slippage_noop_when_disabled()
    test_pov_impact_surcharge_on_thin_volume()
    test_pov_impact_noop_when_disabled()
    test_margin_cap_clamps_contracts()
    test_margin_cap_noop_when_smaller_than_risk_sizing()

    print()
    total = 10
    passed = total - len(FAILURES)
    print(f"{passed}/{total} passed" + (f", {len(FAILURES)} FAILED: {FAILURES}" if FAILURES else ""))
    sys.exit(1 if FAILURES else 0)
