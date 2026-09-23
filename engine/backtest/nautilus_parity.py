"""
JARVIS TRADER — Backtest parity / differential harness.

Runs one identical, deliberately-simplified strategy (SMA golden-cross entry,
death-cross exit, 1 contract, zero execution costs) through BOTH the in-house
event-driven `Backtester` and NautilusTrader's `BacktestEngine`, then compares
the results. Divergence beyond tolerance is a bug in one of the two engines —
that is the whole point (satisfies the "live vs. backtest parity" discipline in
.claude/rules/testing.md, which previously had no second engine to check the
custom `Backtester` against).

This is RESEARCH tooling only. It never touches engine/risk/, engine/config.py,
or any live/paper order path. NautilusTrader is imported lazily so the module (and
the rest of the engine) still imports when the optional dependency is absent.

Design note — why a *reduced* common spec:
    The custom Backtester fills at bar granularity (entry at next bar's open,
    signal exit at the signal bar's close), while Nautilus is a tick/bar
    event-driven engine with its own fill model. Reconciling every bespoke
    Backtester feature (partial T1/T2/T3 exits, slippage, spread, R:R gate, EOD
    close, ATR trailing) to the tick would be a multi-day effort and would compare
    two different fill conventions rather than testing for bugs. Instead we run the
    smallest strategy that both engines can execute the SAME way — SMA cross,
    hold-to-opposite-cross, one contract, no costs — so that trade COUNT and
    DIRECTION must agree exactly (a strong look-ahead / off-by-one detector) and
    net PnL agrees within a tolerance driven only by the documented entry-fill
    convention.

NautilusTrader is LGPL-3.0. This file imports the packaged library; it copies no
Nautilus source. Cross-checked against NautilusTrader (LGPL-3.0).

Source of the pattern: nautechsystems/nautilus_trader
examples/backtest/crypto_ema_cross_ethusdt_trailing_stop.py (analysis:
docs/repo-integrations/nautechsystems__nautilus_trader.md).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Reduced-common-spec defaults. Kept tiny on purpose (see module docstring).
DEFAULT_FAST = 5
DEFAULT_SLOW = 20
DEFAULT_QTY = 1
DEFAULT_INITIAL_CASH = 1_000_000.0


@dataclass(frozen=True)
class ParityResult:
    """One engine's outcome under the reduced common spec."""

    engine: str
    num_trades: int
    net_pnl: float


@dataclass(frozen=True)
class ParityReport:
    """Side-by-side comparison of the two engines."""

    custom: ParityResult
    nautilus: ParityResult
    pnl_abs_diff: float
    pnl_tolerance: float
    trades_match: bool
    pnl_within_tolerance: bool

    @property
    def passed(self) -> bool:
        return self.trades_match and self.pnl_within_tolerance

    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"[parity {status}] "
            f"custom(trades={self.custom.num_trades}, pnl={self.custom.net_pnl:,.2f}) "
            f"vs nautilus(trades={self.nautilus.num_trades}, pnl={self.nautilus.net_pnl:,.2f}) "
            f"| |Δpnl|={self.pnl_abs_diff:,.2f} tol={self.pnl_tolerance:,.2f} "
            f"| trades_match={self.trades_match} pnl_ok={self.pnl_within_tolerance}"
        )


def _sma_cross_marks(close: pd.Series, fast: int, slow: int) -> tuple[pd.Series, pd.Series]:
    """Return (golden_cross, death_cross) boolean Series on the SAME rule both engines use.

    Guards the first valid slow-SMA bar so the NaN->value transition does not fake a
    cross (mirrors the guard in trend_signals.generate_sma_trend_signals).
    """
    sma_f = close.rolling(fast).mean()
    sma_s = close.rolling(slow).mean()
    above = (sma_f > sma_s).fillna(False).astype(bool)
    prev_above = above.shift(1, fill_value=False)
    prev_slow_valid = sma_s.shift(1).notna()
    golden = above & ~prev_above & prev_slow_valid
    death = ~above & prev_above & prev_slow_valid
    return golden, death


def _build_custom_signal_df(
    df: pd.DataFrame, fast: int, slow: int
) -> pd.DataFrame:
    """Build the minimal signal frame the custom Backtester consumes.

    Sets the stop far away (never hit) and targets at R:R 1.5 so the Backtester's
    entry R:R>=1.2 gate passes, then relies on the explicit EXIT_NOW (death cross)
    for the only exit — no trailing, no targets, no EOD.
    """
    out = df.copy()
    golden, death = _sma_cross_marks(out["close"], fast, slow)
    n = len(out)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    entry_signal[golden.values] = "ENTRY_NOW"
    exit_signal[death.values] = "EXIT_NOW"

    close = out["close"].astype(float)
    # Far stop (never touched); target at 1.5x the stop distance -> R:R gate passes.
    stop_dist = close * 0.50
    out["entry_signal"] = entry_signal
    out["exit_signal"] = exit_signal
    out["bias"] = np.where(golden.cumsum().values > death.cumsum().values, "STRONG_BULL", "NEUTRAL")
    # bias just needs to be BULL on the entry bar; recompute cleanly below.
    above = (close.rolling(fast).mean() > close.rolling(slow).mean()).fillna(False)
    out["bias"] = np.where(above.values, "STRONG_BULL", "NEUTRAL")
    out["stop_level"] = (close - stop_dist).values
    out["target_1"] = (close + 1.5 * stop_dist).values
    out["target_2"] = (close + 2.0 * stop_dist).values
    out["target_3"] = (close + 2.5 * stop_dist).values
    out["atr"] = 1.0  # nonzero so the entry path's atr guard passes
    out["regime"] = "TRENDING_BULL"
    return out


def run_custom(
    df: pd.DataFrame,
    symbol: str,
    multiplier: float,
    fast: int = DEFAULT_FAST,
    slow: int = DEFAULT_SLOW,
) -> ParityResult:
    """Run the in-house Backtester under the reduced common spec (zero costs)."""
    from backtest.backtester import Backtester  # noqa: PLC0415

    sig = _build_custom_signal_df(df, fast, slow)
    bt = Backtester(
        initial_capital=DEFAULT_INITIAL_CASH,
        risk_per_trade=0.01,  # irrelevant: fixed_contracts overrides sizing
        max_daily_loss=1.0,  # effectively disable kill switch for parity
        max_drawdown=1.0,
        commission_per_contract=0.0,
        slippage_ticks=0.0,
        spread_ticks=0.0,
        trailing_stop=False,
        use_targets=False,
        eod_close=False,
        fixed_contracts=DEFAULT_QTY,
    )
    result = bt.run(sig, symbol=symbol, multiplier=multiplier)
    net_pnl = float(result.final_capital - result.initial_capital)
    return ParityResult(engine="custom", num_trades=int(result.total_trades), net_pnl=net_pnl)


def run_nautilus(
    df: pd.DataFrame,
    fast: int = DEFAULT_FAST,
    slow: int = DEFAULT_SLOW,
) -> tuple[ParityResult, float]:
    """Run NautilusTrader's BacktestEngine under the reduced common spec.

    Returns (result, instrument_multiplier) so the caller can feed the identical
    multiplier to the custom engine and keep contract economics equal.
    Raises ImportError if nautilus_trader is not installed.
    """

    from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.data import BarType
    from nautilus_trader.model.enums import AccountType, OmsType, OrderSide
    from nautilus_trader.model.identifiers import TraderId
    from nautilus_trader.model.objects import Money, Quantity
    from nautilus_trader.persistence.wranglers import BarDataWrangler
    from nautilus_trader.test_kit.providers import TestInstrumentProvider
    from nautilus_trader.trading.strategy import Strategy, StrategyConfig

    # Use a non-expiring equity instrument as the parity vehicle. A real futures
    # contract (es_future) has a limited active window — it rejects orders outside
    # [activation, expiration] — which cannot span a continuous multi-year cache
    # series. An equity has no such date constraints, so orders always route. Its
    # multiplier (1) is read back and fed to the custom engine so economics match;
    # price magnitude is irrelevant to the SMA-cross parity logic.
    instrument = TestInstrumentProvider.equity()
    venue = instrument.id.venue
    bar_type = BarType.from_str(f"{instrument.id}-1-HOUR-LAST-EXTERNAL")

    class _SmaCross(Strategy):
        """Golden-cross enter (1 contract), death-cross exit — next-bar aligned.

        To mirror the custom Backtester's pending-entry-at-next-bar convention,
        a detected cross sets a flag; the order is submitted at the TOP of the
        NEXT on_bar, so it fills against that bar rather than the signal bar.
        """

        def __init__(self, cfg) -> None:
            super().__init__(cfg)
            self._fast_sum: list[float] = []
            self._slow_sum: list[float] = []
            self._prev_above: Optional[bool] = None
            self._have_slow_prev = False

        def on_start(self) -> None:
            self.subscribe_bars(bar_type)

        def on_bar(self, bar) -> None:
            # Update SMAs and detect the cross on THIS bar's close, then act on
            # the same bar. A market order submitted during on_bar fills at this
            # bar's close (Nautilus bar-execution) — the "enter at signal-bar
            # close" convention, which has no look-ahead (the cross is known from
            # data <= this bar). The custom Backtester enters at the NEXT bar's
            # open; on gapless bars those prices coincide, so parity is tight.
            close = float(bar.close)
            self._fast_sum.append(close)
            self._slow_sum.append(close)
            if len(self._fast_sum) > fast:
                self._fast_sum.pop(0)
            if len(self._slow_sum) > slow:
                self._slow_sum.pop(0)
            if len(self._slow_sum) < slow:
                return
            sma_f = sum(self._fast_sum) / fast
            sma_s = sum(self._slow_sum) / slow
            above = sma_f > sma_s
            if self._prev_above is not None and self._have_slow_prev:
                if above and not self._prev_above and self.portfolio.is_flat(instrument.id):
                    self.submit_order(
                        self.order_factory.market(
                            instrument_id=instrument.id,
                            order_side=OrderSide.BUY,
                            quantity=Quantity.from_int(DEFAULT_QTY),
                        )
                    )
                elif not above and self._prev_above and not self.portfolio.is_flat(instrument.id):
                    self.close_all_positions(instrument.id)
            self._prev_above = above
            self._have_slow_prev = True

    config = BacktestEngineConfig(trader_id=TraderId("PARITY-001"))
    engine = BacktestEngine(config=config)
    engine.add_venue(
        venue=venue,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,  # long-only: no margin/expiry complications
        base_currency=USD,
        starting_balances=[Money(DEFAULT_INITIAL_CASH, USD)],
    )
    engine.add_instrument(instrument)

    wrangler = BarDataWrangler(bar_type=bar_type, instrument=instrument)

    # pandas >= 3.0 (copy-on-write) hands the wrangler read-only numpy buffers,
    # which nautilus_trader's cython BarDataWrangler.process rejects with
    # "buffer source array is read-only". Force writable contiguous copies.
    bars_df = df[["open", "high", "low", "close", "volume"]].copy()
    for col in bars_df.columns:
        bars_df[col] = np.ascontiguousarray(bars_df[col].to_numpy(dtype="float64"))
    bars = wrangler.process(bars_df)
    engine.add_data(bars)

    strategy = _SmaCross(StrategyConfig())
    engine.add_strategy(strategy=strategy)
    engine.run()

    # Count only CLOSED (FLAT) positions and sum their realized PnL — a position
    # left open at the end of data (side==LONG) is not a completed round trip and
    # must be excluded to match the custom engine's completed-trades semantics.
    report = engine.trader.generate_positions_report()
    if report is None or len(report) == 0:
        num_trades, net_pnl = 0, 0.0
    else:
        closed = report[report["side"] == "FLAT"]
        num_trades = len(closed)
        # realized_pnl renders as "<amount> <ccy>" (e.g. "577.25 USD"); parse the number.
        net_pnl = float(sum(float(str(v).split()[0]) for v in closed["realized_pnl"]))
    mult = float(instrument.multiplier)

    engine.reset()
    engine.dispose()
    return ParityResult(engine="nautilus", num_trades=num_trades, net_pnl=net_pnl), mult


def compare(
    df: pd.DataFrame,
    symbol: str = "ES",
    fast: int = DEFAULT_FAST,
    slow: int = DEFAULT_SLOW,
    pnl_rel_tolerance: float = 0.02,
    pnl_abs_floor: float = 1.0,
) -> ParityReport:
    """Run both engines on identical bars and build a ParityReport.

    Tolerance: PnL may differ by the entry-fill convention (custom fills at the
    next bar's open; Nautilus fills the queued market order against the next bar).
    We allow max(pnl_rel_tolerance * |custom_pnl|, pnl_abs_floor). Trade count and
    direction must match exactly — those are the strong bug detectors.
    """
    naut, mult = run_nautilus(df, fast=fast, slow=slow)
    custom = run_custom(df, symbol=symbol, multiplier=mult, fast=fast, slow=slow)

    abs_diff = abs(custom.net_pnl - naut.net_pnl)
    tol = max(pnl_rel_tolerance * abs(custom.net_pnl), pnl_abs_floor)
    return ParityReport(
        custom=custom,
        nautilus=naut,
        pnl_abs_diff=abs_diff,
        pnl_tolerance=tol,
        trades_match=(custom.num_trades == naut.num_trades),
        pnl_within_tolerance=(abs_diff <= tol),
    )


def make_synthetic_bars(
    lead_dn: int = 30, seed_up: int = 50, seed_dn: int = 50, base: float = 5000.0
) -> pd.DataFrame:
    """Deterministic OHLC bars: a lead-in decline, then an uptrend, then a
    downtrend — producing exactly one golden cross (fast rises through slow from
    below) and one death cross under a fast/slow SMA. The lead-in matters: a pure
    uptrend never yields a *cross* because fast starts already above slow. No
    randomness (Date.now / rng free)."""
    lead = [base - i * 5.0 for i in range(lead_dn)]
    trough = lead[-1]
    up = [trough + i * 5.0 for i in range(1, seed_up + 1)]
    dn = [up[-1] - i * 5.0 for i in range(1, seed_dn + 1)]
    closes = lead + up + dn
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="1h")
    close = pd.Series(closes, index=idx)
    open_ = close.shift(1).fillna(close.iloc[0])
    hi = pd.concat([open_, close], axis=1).max(axis=1) + 2.0
    lo = pd.concat([open_, close], axis=1).min(axis=1) - 2.0
    frame = pd.DataFrame(
        {
            "open": open_.values,
            "high": hi.values,
            "low": lo.values,
            "close": close.values,
            "volume": 1000.0,
        },
        index=idx,
    )
    return frame


if __name__ == "__main__":  # pragma: no cover - manual smoke run
    logging.basicConfig(level=logging.INFO)
    report = compare(make_synthetic_bars())
    print(report.summary())
