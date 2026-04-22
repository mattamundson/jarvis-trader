"""
JARVIS TRADER — Options Strategy Backtester Scaffold (Strategy Novel #3)
========================================================================
Replay historical options chains against existing futures signal timestamps
to evaluate defined-risk option overlays (e.g. vertical spreads on MES).

Source: docs/digest/strategy-synthesis.md Novel #3 (@pyquantnews / Optopsy).

Design intent
-------------
Existing `engine/options/` has live chain pricing and Greeks but NO
offline replay. This scaffold provides the orchestration layer:

  signals  → ChainProvider (historical) → strategy selector
           → SlippageModel              → fills
           → exit rule                  → realised P&L

Production binds:
  ChainProvider   ← engine/options/chain_fetcher.py historical mode
  SignalSource    ← engine/backtest/composite_signals.py timestamps
  SlippageModel   ← spread/2 + configurable bps

Tests bind:
  ChainProvider   ← in-memory dict[(symbol, ts) → OptionsChain]
  SignalSource    ← list[(ts, side)]
  SlippageModel   ← deterministic constant

Strategy coverage (this scaffold)
---------------------------------
* `select_vertical_spread(chain, direction, target_delta, width_strikes)` —
  picks two strikes for a debit (bull call / bear put) or credit
  (bear call / bull put) vertical. Width measured in strike units.

DEFERRED to follow-up:
* Covered calls (require underlying-position tracking — different concern)
* Iron condors / butterflies (multi-leg coordination)
* Early-exit rules other than expiry intrinsic (e.g. 50% profit, 21 DTE)
* Full chain replay against the existing 2024–2025 MCL/MES signal set
* Slippage model calibration against historical fills

NOT live-wired
--------------
This is an offline research tool. It does NOT modify trader.py,
pipeline.py, or risk_manager.py. Promoting an option-overlay finding
to production is a separate human-reviewed PR — see
`.claude/rules/commits.md` for the Tier 3 process.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional, Protocol

# Reuse the existing data contract — DO NOT duplicate
from options.chain_fetcher import OptionsChain, OptionsContract

logger = logging.getLogger(__name__)

__all__ = [
    "Signal",
    "OptionsLeg",
    "VerticalSpread",
    "BacktestTrade",
    "BacktestResult",
    "ChainProvider",
    "SignalSource",
    "SlippageModel",
    "FlatSlippage",
    "select_vertical_spread",
    "OptionsBacktester",
]


# ── Signal + leg + spread + trade dataclasses ───────────────────────────────

@dataclass(frozen=True)
class Signal:
    """One signal timestamp from the futures pipeline that the option
    overlay should act on."""

    timestamp: datetime
    symbol: str           # underlying (e.g. "MES")
    side: str             # "LONG" | "SHORT" — direction of the futures view
    confidence: float = 0.5  # [0, 1] — used for sizing; default = neutral


@dataclass
class OptionsLeg:
    """One leg of a multi-leg position."""

    contract: OptionsContract
    quantity: int                # positive = long, negative = short
    entry_price: float           # per-contract premium paid/received
    entry_timestamp: datetime
    exit_price: float = 0.0
    exit_timestamp: Optional[datetime] = None

    @property
    def is_open(self) -> bool:
        return self.exit_timestamp is None

    @property
    def realised_pnl(self) -> float:
        """P&L per leg, signed by quantity direction. Returns 0 while open."""
        if self.is_open:
            return 0.0
        return (self.exit_price - self.entry_price) * self.quantity


@dataclass
class VerticalSpread:
    """A two-leg vertical spread (debit or credit).

    Convention:
      * Bull call (debit): long lower-strike call + short higher-strike call
      * Bear put (debit):  long higher-strike put  + short lower-strike put
      * Bear call (credit): short lower-strike call + long higher-strike call
      * Bull put (credit):  short higher-strike put + long lower-strike put

    Net debit = sum(entry_price * quantity) for long legs minus shorts.
    """

    long_leg: OptionsLeg
    short_leg: OptionsLeg

    @property
    def net_debit(self) -> float:
        """Per-spread cost (positive = debit, negative = credit)."""
        return self.long_leg.entry_price - self.short_leg.entry_price

    @property
    def max_profit(self) -> float:
        """Distance between strikes minus debit (for debit spreads)."""
        width = abs(self.long_leg.contract.strike - self.short_leg.contract.strike)
        return width - self.net_debit

    @property
    def max_loss(self) -> float:
        """For a debit spread, max loss = net debit. For credit, = width - credit."""
        if self.net_debit >= 0:
            return self.net_debit
        width = abs(self.long_leg.contract.strike - self.short_leg.contract.strike)
        return width + self.net_debit  # net_debit is negative here

    @property
    def is_open(self) -> bool:
        return self.long_leg.is_open or self.short_leg.is_open

    @property
    def realised_pnl(self) -> float:
        return self.long_leg.realised_pnl + self.short_leg.realised_pnl


@dataclass
class BacktestTrade:
    """One closed spread + the signal that opened it."""

    signal: Signal
    spread: VerticalSpread

    @property
    def pnl_usd(self) -> float:
        return self.spread.realised_pnl

    @property
    def is_winner(self) -> bool:
        return self.pnl_usd > 0


@dataclass
class BacktestResult:
    """Aggregate stats over all closed trades."""

    trades: list[BacktestTrade] = field(default_factory=list)
    n_signals_consumed: int = 0
    n_signals_skipped_no_chain: int = 0
    n_signals_skipped_no_strikes: int = 0

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl_usd for t in self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t.is_winner) / len(self.trades)

    @property
    def profit_factor(self) -> float:
        gross_win = sum(t.pnl_usd for t in self.trades if t.pnl_usd > 0)
        gross_loss = -sum(t.pnl_usd for t in self.trades if t.pnl_usd < 0)
        if gross_loss == 0:
            return float("inf") if gross_win > 0 else 0.0
        return gross_win / gross_loss

    def to_dict(self) -> dict:
        return {
            "n_trades": self.n_trades,
            "total_pnl": round(self.total_pnl, 2),
            "win_rate": round(self.win_rate, 4),
            "profit_factor": (
                round(self.profit_factor, 4)
                if self.profit_factor != float("inf")
                else "inf"
            ),
            "n_signals_consumed": self.n_signals_consumed,
            "n_signals_skipped_no_chain": self.n_signals_skipped_no_chain,
            "n_signals_skipped_no_strikes": self.n_signals_skipped_no_strikes,
        }


# ── Protocols (allows mocking in tests, real adapters in prod) ──────────────

class ChainProvider(Protocol):
    """Supplies a chain for (symbol, timestamp). Returns None if no chain
    is available at that timestamp (e.g. weekend, before listing)."""

    def get_chain(
        self,
        symbol: str,
        as_of: datetime,
        target_dte: int,
    ) -> Optional[OptionsChain]:
        ...


class SignalSource(Protocol):
    """Yields signals to act on, in chronological order."""

    def signals(self) -> list[Signal]:
        ...


class SlippageModel(Protocol):
    """Converts a mid-price to an expected fill price for one leg."""

    def fill_price(self, contract: OptionsContract, side: str) -> float:
        """side: 'BUY' or 'SELL'. Returns the price per contract."""
        ...


# ── Default slippage implementation ─────────────────────────────────────────

@dataclass
class FlatSlippage:
    """
    Symmetric slippage: BUY fills at mid + half-spread + bps; SELL at
    mid - half-spread - bps. For options the half-spread term often
    dominates — bps is a residual market-impact buffer.
    """

    bps: float = 5.0  # additional drag in basis points of mid

    def fill_price(self, contract: OptionsContract, side: str) -> float:
        mid = contract.mid if contract.mid > 0 else (contract.bid + contract.ask) / 2
        half_spread = max(0.0, (contract.ask - contract.bid) / 2)
        bps_drag = mid * (self.bps / 10_000)
        if side.upper() == "BUY":
            return round(mid + half_spread + bps_drag, 4)
        if side.upper() == "SELL":
            return round(max(0.0, mid - half_spread - bps_drag), 4)
        raise ValueError(f"Unknown side: {side!r} (expected 'BUY' or 'SELL')")


# ── Strike selection ────────────────────────────────────────────────────────

def select_vertical_spread(
    chain: OptionsChain,
    direction: str,
    target_delta: float = 0.30,
    width_strikes: int = 1,
) -> Optional[tuple[OptionsContract, OptionsContract]]:
    """
    Pick (long_leg_contract, short_leg_contract) for a debit vertical spread.

    direction: "BULL" → bull call spread (long + short calls)
               "BEAR" → bear put spread  (long + short puts)
    target_delta: absolute delta of the long leg (e.g. 0.30 = 30-delta)
    width_strikes: how many strikes apart short leg sits (1 = adjacent strikes)

    Returns None if the chain doesn't have enough strikes to build the spread.
    """
    if direction.upper() not in {"BULL", "BEAR"}:
        raise ValueError(f"direction must be 'BULL' or 'BEAR', got {direction!r}")
    if target_delta <= 0 or target_delta >= 1:
        raise ValueError(f"target_delta must be in (0, 1), got {target_delta}")
    if width_strikes < 1:
        raise ValueError(f"width_strikes must be >= 1, got {width_strikes}")

    is_bull = direction.upper() == "BULL"
    contracts = list(chain.calls) if is_bull else list(chain.puts)
    if not contracts:
        return None

    # Find the long leg by closest |delta| to target
    long_leg = min(contracts, key=lambda c: abs(abs(c.delta) - target_delta))

    # Sort strikes to find the short leg `width_strikes` away
    sorted_strikes = sorted({c.strike for c in contracts})
    if long_leg.strike not in sorted_strikes:
        return None
    long_idx = sorted_strikes.index(long_leg.strike)

    # Bull call: short leg is HIGHER strike (further OTM)
    # Bear put:  short leg is LOWER  strike (further OTM)
    short_idx = long_idx + width_strikes if is_bull else long_idx - width_strikes
    if short_idx < 0 or short_idx >= len(sorted_strikes):
        return None
    short_strike = sorted_strikes[short_idx]
    short_candidates = [c for c in contracts if c.strike == short_strike]
    if not short_candidates:
        return None
    short_leg = short_candidates[0]

    return (long_leg, short_leg)


# ── The backtester ──────────────────────────────────────────────────────────

class OptionsBacktester:
    """
    Replays signals against historical chains, opens debit vertical spreads,
    holds to expiry, computes intrinsic value at exit, and aggregates results.

    Hold-to-expiry is the simplest exit rule — early-exit (e.g. 50%
    profit-target, 21-DTE roll) is deferred follow-up work.
    """

    def __init__(
        self,
        chain_provider: ChainProvider,
        signal_source: SignalSource,
        slippage_model: Optional[SlippageModel] = None,
        *,
        target_dte: int = 30,
        target_delta: float = 0.30,
        width_strikes: int = 1,
        contracts_per_signal: int = 1,
    ):
        if target_dte < 1:
            raise ValueError(f"target_dte must be >= 1, got {target_dte}")
        if contracts_per_signal < 1:
            raise ValueError(
                f"contracts_per_signal must be >= 1, got {contracts_per_signal}"
            )

        self.chain_provider = chain_provider
        self.signal_source = signal_source
        self.slippage_model = slippage_model or FlatSlippage()
        self.target_dte = target_dte
        self.target_delta = target_delta
        self.width_strikes = width_strikes
        self.contracts_per_signal = contracts_per_signal

    # ── Open one spread for one signal ───────────────────────────────────

    def _open_spread(self, signal: Signal) -> Optional[VerticalSpread]:
        chain = self.chain_provider.get_chain(
            signal.symbol, signal.timestamp, self.target_dte
        )
        if chain is None:
            return None

        direction = "BULL" if signal.side.upper() == "LONG" else "BEAR"
        picks = select_vertical_spread(
            chain,
            direction=direction,
            target_delta=self.target_delta,
            width_strikes=self.width_strikes,
        )
        if picks is None:
            return None

        long_contract, short_contract = picks
        long_fill = self.slippage_model.fill_price(long_contract, "BUY")
        short_fill = self.slippage_model.fill_price(short_contract, "SELL")

        long_leg = OptionsLeg(
            contract=long_contract,
            quantity=self.contracts_per_signal,
            entry_price=long_fill,
            entry_timestamp=signal.timestamp,
        )
        short_leg = OptionsLeg(
            contract=short_contract,
            quantity=-self.contracts_per_signal,
            entry_price=short_fill,
            entry_timestamp=signal.timestamp,
        )
        return VerticalSpread(long_leg=long_leg, short_leg=short_leg)

    # ── Close one spread at expiry (intrinsic value) ─────────────────────

    @staticmethod
    def _intrinsic_value(contract: OptionsContract, underlying_at_expiry: float) -> float:
        if contract.option_type == "call":
            return max(0.0, underlying_at_expiry - contract.strike)
        if contract.option_type == "put":
            return max(0.0, contract.strike - underlying_at_expiry)
        raise ValueError(f"Unknown option_type: {contract.option_type!r}")

    def _close_spread_at_expiry(
        self,
        spread: VerticalSpread,
        underlying_at_expiry: float,
    ) -> None:
        """Close both legs at intrinsic value. Mutates spread in place."""
        expiry = spread.long_leg.contract.expiry
        exit_ts = datetime.combine(expiry, datetime.min.time())

        for leg in (spread.long_leg, spread.short_leg):
            leg.exit_price = self._intrinsic_value(leg.contract, underlying_at_expiry)
            leg.exit_timestamp = exit_ts

    # ── Main loop ────────────────────────────────────────────────────────

    def run(
        self,
        underlying_prices_at_expiry: dict[date, float],
    ) -> BacktestResult:
        """
        Replay all signals. `underlying_prices_at_expiry` maps each expiry
        date that gets used to the underlying close on that date — supplied
        by the caller because it's market-data-source dependent.
        """
        result = BacktestResult()
        for signal in self.signal_source.signals():
            result.n_signals_consumed += 1
            spread = self._open_spread(signal)
            if spread is None:
                # Differentiate the two skip reasons by re-checking why
                if self.chain_provider.get_chain(
                    signal.symbol, signal.timestamp, self.target_dte
                ) is None:
                    result.n_signals_skipped_no_chain += 1
                else:
                    result.n_signals_skipped_no_strikes += 1
                continue

            expiry = spread.long_leg.contract.expiry
            if expiry not in underlying_prices_at_expiry:
                logger.warning(
                    "no underlying price at expiry %s for %s — skipping close",
                    expiry, signal.symbol,
                )
                continue

            self._close_spread_at_expiry(
                spread, underlying_prices_at_expiry[expiry]
            )
            result.trades.append(BacktestTrade(signal=signal, spread=spread))

        return result
