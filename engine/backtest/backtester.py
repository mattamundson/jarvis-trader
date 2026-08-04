"""
JARVIS TRADER — Event-Driven Backtester
Walk-forward simulation of the 5-layer trading strategy.

Domain models (Trade, BacktestResult) live in trade_manager.py.
Metrics computation lives in metrics.py.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from backtest.metrics import calculate_metrics

# Re-export for backward compatibility — all existing imports continue to work
from backtest.trade_manager import BacktestResult, Trade

# Lazy import to avoid circular dependency; resolved at first use
_settings = None


def _get_settings():
    global _settings
    if _settings is None:
        from config import settings  # noqa: PLC0415

        _settings = settings
    return _settings


__all__ = ["Backtester", "BacktestResult", "Trade"]


# Tick sizes by symbol type
TICK_SIZES: Dict[str, float] = {
    "ES": 0.25,
    "MES": 0.25,
    "NQ": 0.25,
    "MNQ": 0.25,
    "YM": 1.0,
    "MYM": 1.0,
    "RTY": 0.10,
    "M2K": 0.10,
    "CL": 0.01,
    "GC": 0.10,
    "MGC": 0.10,
    "MCL": 0.01,
}
DEFAULT_TICK_SIZE_FUTURES = 0.25
DEFAULT_TICK_SIZE_ETF = 0.01


class Backtester:
    """Event-driven walk-forward backtester."""

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        risk_per_trade: float = 0.03,  # $10K aggressive profile (2026-06-25, Amo-directed; see ror_sweep)
        max_daily_loss: float = 0.06,  # aggressive $10K (3x prior 0.02), matches config/.env
        max_drawdown: float = 0.20,  # reconciled to live .env ceiling (was 0.05 backtest breaker)
        t1_exit_pct: float = 0.50,  # % to exit at target 1
        t2_exit_pct: float = 0.30,  # % to exit at target 2
        commission_per_contract: Optional[float] = None,
        slippage_ticks: Optional[float] = None,
        spread_ticks: Optional[float] = None,
        trailing_stop: bool = False,
        trailing_atr_mult: float = 0.70,
        trailing_post_t1: bool = False,
        strict_trailing: bool = False,
        eod_close: bool = True,
        use_targets: bool = True,
        fixed_contracts: Optional[int] = None,
        # ── SOTA execution-realism hardening (2026-08-04) — all optional, all
        # default to current (unchanged) behavior. See docs/backtest-sota-hardening.md.
        pessimistic_tie_breaker: bool = False,
        volatility_scaled_slippage: bool = False,
        vol_slippage_lookback: int = 20,
        vol_slippage_min_mult: float = 0.5,
        vol_slippage_max_mult: float = 4.0,
        initial_margin_per_contract: Optional[float] = None,
        max_volume_pct: Optional[float] = None,
        gap_stop_worst_fill: bool = False,
    ):
        self.initial_capital = initial_capital
        self.risk_per_trade = risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_drawdown = max_drawdown
        self.t1_exit_pct = t1_exit_pct
        self.t2_exit_pct = t2_exit_pct
        # Pull from config if not explicitly overridden by caller
        cfg = _get_settings()
        self.commission_per_contract = (
            commission_per_contract
            if commission_per_contract is not None
            else cfg.COMMISSION_PER_CONTRACT
        )
        self.slippage_ticks = slippage_ticks if slippage_ticks is not None else cfg.SLIPPAGE_TICKS
        self.spread_ticks = spread_ticks if spread_ticks is not None else cfg.SPREAD_TICKS
        self.trailing_stop = trailing_stop
        self.trailing_atr_mult = trailing_atr_mult
        self.trailing_post_t1 = trailing_post_t1
        # strict_trailing=True: update trail on every bar (no favorable_excursion gate),
        # matching the WFO custom backtester behavior for trend-following strategies.
        self.strict_trailing = strict_trailing
        # eod_close=False: hold positions overnight (trend strategies). True = intraday only.
        self.eod_close = eod_close
        # use_targets=False: never exit at fixed price targets (trend-following only).
        self.use_targets = use_targets
        # fixed_contracts: override ATR-based sizing. Set to 1 for trend strategies to
        # match WFO equal-weight basis (ATR sizing inverts trend edge: small-ATR → more
        # contracts → amplified losses; large-ATR/trending → fewer contracts → muted wins).
        self.fixed_contracts = fixed_contracts

        # pessimistic_tie_breaker=True: on a bar where BOTH the stop and a target are
        # touched, always assume the stop was hit first (worst-case ordering) instead of
        # inferring from bar_open direction. Default False preserves existing
        # target_first-from-open behavior exactly (see _process_bar_exits).
        self.pessimistic_tie_breaker = pessimistic_tie_breaker

        # volatility_scaled_slippage=True: scale slippage_ticks by the ratio of the
        # current bar's ATR to a trailing mean ATR (clamped to
        # [vol_slippage_min_mult, vol_slippage_max_mult]), so slippage widens during
        # volatility spikes instead of staying flat. Default False = flat slippage_ticks
        # (unchanged behavior).
        self.volatility_scaled_slippage = volatility_scaled_slippage
        self.vol_slippage_lookback = vol_slippage_lookback
        self.vol_slippage_min_mult = vol_slippage_min_mult
        self.vol_slippage_max_mult = vol_slippage_max_mult

        # gap_stop_worst_fill=True: if the bar's OPEN already violates the stop level
        # (a gap through the stop), fill at the worse of (bar_open, stop_price) instead
        # of always assuming a fill exactly at stop_price. Default False preserves
        # existing behavior (fill at stop_price regardless of gap).
        self.gap_stop_worst_fill = gap_stop_worst_fill

        # initial_margin_per_contract: if set, caps contracts so
        # contracts * initial_margin_per_contract <= available capital, in addition to
        # (not instead of) the existing risk-based sizing in _calculate_contracts.
        # None (default) = no margin cap (unchanged behavior).
        self.initial_margin_per_contract = initial_margin_per_contract

        # max_volume_pct: if set (e.g. 0.10 for 10% POV), caps contracts to
        # max_volume_pct * bar_volume when the bar carries a real "volume" column, and
        # applies an Almgren-Chriss-style quadratic temporary-impact slippage surcharge
        # when a fill's requested size exceeds that cap. None (default) = no POV cap or
        # impact surcharge (unchanged behavior).
        self.max_volume_pct = max_volume_pct

    def _pov_impact_multiplier(self, contracts: int, bar_volume: Optional[float]) -> float:
        """Almgren-Chriss-style quadratic temporary impact multiplier for slippage.

        Returns 1.0 (no extra impact) unless max_volume_pct is set AND the bar carries
        a usable volume figure. When both are true, orders that exceed the POV cap pay
        a slippage surcharge that grows with the SQUARE of how far size exceeds the cap
        — modeling the fact that market impact accelerates non-linearly as an order
        consumes more of the available liquidity in one bar.
        """
        if self.max_volume_pct is None or not bar_volume or bar_volume <= 0:
            return 1.0
        pov = contracts / bar_volume
        if pov <= self.max_volume_pct:
            return 1.0
        excess_ratio = pov / self.max_volume_pct
        return 1.0 + (excess_ratio - 1.0) ** 2

    def _volatility_slippage_multiplier(self, bar_atr: float, mean_atr: Optional[float]) -> float:
        """Ratio of current-bar ATR to trailing mean ATR, clamped to configured bounds.

        Returns 1.0 (flat, unchanged behavior) unless volatility_scaled_slippage=True
        and a valid mean_atr is available.
        """
        if not self.volatility_scaled_slippage or not mean_atr or mean_atr <= 0:
            return 1.0
        raw_mult = bar_atr / mean_atr
        return max(self.vol_slippage_min_mult, min(self.vol_slippage_max_mult, raw_mult))

    def _margin_capped_contracts(self, contracts: int, capital: float) -> int:
        """Clamp contracts so contracts * initial_margin_per_contract <= capital.

        No-op (returns contracts unchanged) unless initial_margin_per_contract is set.
        Applied ON TOP OF (never instead of) the existing risk-based sizing — this is a
        hard ceiling, not a replacement sizing model.
        """
        if self.initial_margin_per_contract is None or self.initial_margin_per_contract <= 0:
            return contracts
        max_by_margin = int(capital // self.initial_margin_per_contract)
        return max(0, min(contracts, max_by_margin))

    def _trailing_mean_atr(self, df: pd.DataFrame, idx) -> Optional[float]:
        """Mean of the ``atr`` column over the vol_slippage_lookback bars prior to idx.

        Returns None (→ multiplier of 1.0, unchanged behavior) if the frame has no
        ``atr`` column or there isn't at least one prior bar to average.
        """
        if "atr" not in df.columns:
            return None
        try:
            pos = df.index.get_loc(idx)
        except KeyError:
            return None
        if isinstance(pos, slice) or pos <= 0:
            return None
        start = max(0, pos - self.vol_slippage_lookback)
        window = df["atr"].iloc[start:pos]
        window = window.dropna()
        if window.empty:
            return None
        return float(window.mean())

    def _apply_slippage(
        self, price: float, direction: str, tick_size: float, slippage_ticks: float
    ) -> float:
        """Long entries pay up, short entries get worse fills. Realistic 1-tick adverse selection."""
        pts = tick_size * slippage_ticks
        return price + pts if direction == "long" else price - pts

    def _apply_execution_costs(
        self,
        price: float,
        direction: str,
        tick_size: float,
        slippage_ticks: float,
        spread_ticks: float,
    ) -> float:
        """
        Apply both adverse slippage AND half-spread to fill price.

        Adverse slippage: we get a worse price than mid (1 tick by default).
        Spread cost: we cross the spread on entry (buy at ask, sell at bid).
        Both apply on entry; on exit, spread applies again (crossing the other side).
        Net effect: each fill costs (slippage_ticks + spread_ticks) * tick_size more than mid.
        """
        total_adverse_ticks = slippage_ticks + spread_ticks
        adverse_pts = tick_size * total_adverse_ticks
        if direction == "long":
            return price + adverse_pts  # Long entry: pay up (ask side + slippage)
        else:
            return price - adverse_pts  # Short entry: sell down (bid side + slippage)

    def _exit_spread_cost(self, contracts: int, tick_size: float, multiplier: float) -> float:
        """
        Spread cost on exit fill: we cross the spread again when closing.
        Long exit → sell at bid (mid - half_spread). Short exit → buy at ask (mid + half_spread).
        Cost = contracts * spread_ticks * tick_size * multiplier.
        """
        cfg = _get_settings()
        if not cfg.SPREAD_ENABLED:
            return 0.0
        return contracts * self.spread_ticks * tick_size * multiplier

    def _round_trip_cost(self, contracts: int, commission_per_contract: float) -> float:
        """Full round-trip commission (entry + exit combined)."""
        return contracts * commission_per_contract

    def _transaction_cost(self, contracts: int, tick_size: float = 0.25) -> float:
        """Round-trip commission cost per contract.
        Note: slippage is applied as adverse fill price in _apply_execution_costs(), not doubled here.
              Exit spread cost is applied separately via _exit_spread_cost().
        """
        cfg = _get_settings()
        return (
            self._round_trip_cost(contracts, self.commission_per_contract)
            if cfg.COMMISSION_ENABLED
            else 0.0
        )

    def _get_tick_size(self, symbol: str, multiplier: float) -> float:
        """Determine tick size from symbol or multiplier heuristic."""
        base = symbol.replace("=F", "").replace("-F", "").upper()
        if base in TICK_SIZES:
            return TICK_SIZES[base]
        if multiplier <= 1.0:
            return DEFAULT_TICK_SIZE_ETF
        return DEFAULT_TICK_SIZE_FUTURES

    def _calculate_contracts(
        self, capital: float, entry: float, stop: float, multiplier: float
    ) -> int:
        """contracts = (capital x risk%) / (stop_distance x multiplier), then clamped
        to the initial-margin ceiling when initial_margin_per_contract is set."""
        stop_dist = abs(entry - stop)
        if stop_dist <= 0 or multiplier <= 0:
            return 0
        risk_dollars = capital * self.risk_per_trade
        contracts = risk_dollars / (stop_dist * multiplier)
        contracts = max(0, min(int(contracts), 50))  # cap at 50
        return self._margin_capped_contracts(contracts, capital)

    def _process_pending_entry(
        self,
        pending_entry: dict,
        row: pd.Series,
        idx,
        df: pd.DataFrame,
        multiplier: float,
        tick_size: float,
    ) -> tuple[Optional[Trade], int, int, int, list, float]:
        """Process a pending entry signal (avoid look-ahead bias)."""
        raw_entry_price = row["open"]
        atr_val = pending_entry["atr"]
        direction = pending_entry["direction"]

        # Apply execution costs (adverse slippage + half-spread) on the fill price.
        # slippage_ticks is optionally scaled by current-vs-trailing-mean ATR
        # (volatility_scaled_slippage) and by a POV/impact surcharge
        # (max_volume_pct) before being applied — both no-ops unless configured.
        cfg = _get_settings()
        effective_spread = self.spread_ticks if cfg.SPREAD_ENABLED else 0.0
        effective_slippage_ticks = self.slippage_ticks if cfg.SLIPPAGE_ENABLED else 0.0
        if effective_slippage_ticks and self.volatility_scaled_slippage:
            mean_atr = self._trailing_mean_atr(df, idx)
            effective_slippage_ticks *= self._volatility_slippage_multiplier(atr_val, mean_atr)
        if effective_slippage_ticks and self.max_volume_pct is not None:
            approx_contracts = (
                self.fixed_contracts
                if self.fixed_contracts is not None
                else self._calculate_contracts(
                    row.get("capital", self.initial_capital),
                    raw_entry_price,
                    raw_entry_price - pending_entry["stop_atr_mult"] * atr_val
                    if direction == "long"
                    else raw_entry_price + pending_entry["stop_atr_mult"] * atr_val,
                    multiplier,
                )
            )
            effective_slippage_ticks *= self._pov_impact_multiplier(
                approx_contracts, row.get("volume")
            )
        if cfg.SLIPPAGE_ENABLED or cfg.SPREAD_ENABLED:
            entry_price = self._apply_execution_costs(
                raw_entry_price,
                direction,
                tick_size,
                effective_slippage_ticks,
                effective_spread,
            )
        else:
            entry_price = raw_entry_price

        # Recalculate stop and targets from actual entry price (post-slippage)
        if direction == "long":
            stop_price = entry_price - pending_entry["stop_atr_mult"] * atr_val
            target_1 = entry_price + pending_entry["t1_atr_mult"] * atr_val
            target_2 = entry_price + pending_entry["t2_atr_mult"] * atr_val
        else:
            stop_price = entry_price + pending_entry["stop_atr_mult"] * atr_val
            target_1 = entry_price - pending_entry["t1_atr_mult"] * atr_val
            target_2 = entry_price - pending_entry["t2_atr_mult"] * atr_val

        stop_dist = abs(entry_price - stop_price)
        if stop_dist <= 0:
            return None, 0, 0, 0, [], 0.0

        rr = abs(target_1 - entry_price) / stop_dist
        if rr < 1.2:
            return None, 0, 0, 0, [], 0.0

        if self.fixed_contracts is not None:
            total_contracts = self.fixed_contracts
        else:
            total_contracts = self._calculate_contracts(
                row.get("capital", self.initial_capital), entry_price, stop_price, multiplier
            )
        if total_contracts < 1:
            return None, 0, 0, 0, [], 0.0

        t1_contracts = max(1, int(total_contracts * self.t1_exit_pct))
        t2_contracts = max(0, int(total_contracts * self.t2_exit_pct))
        t3_contracts = max(0, total_contracts - t1_contracts - t2_contracts)

        open_trade = Trade(
            entry_date=idx,
            symbol=row.get("symbol", ""),
            direction=direction,
            entry_price=entry_price,
            stop_price=stop_price,
            target_1=target_1,
            target_2=target_2,
            contracts=total_contracts,
            multiplier=multiplier,
            regime=pending_entry.get("regime", ""),
            bias=pending_entry["bias"],
        )
        capital_used = self._transaction_cost(total_contracts, tick_size)
        return open_trade, t1_contracts, t2_contracts, t3_contracts, [], capital_used

    def _check_targets_exit(
        self,
        open_trade: Trade,
        open_contracts_t1: int,
        open_contracts_t2: int,
        multiplier: float,
        tick_size: float,
        t1_touched: bool,
        t2_touched: bool,
    ) -> tuple[int, int, float, list]:
        """Check and process target exits."""
        if not self.use_targets:
            return open_contracts_t1, open_contracts_t2, 0.0, []
        targets_hit = []
        capital_change = 0.0

        if open_contracts_t1 > 0 and t1_touched:
            exit_price = open_trade.target_1
            if open_trade.direction == "long":
                pnl = open_contracts_t1 * (exit_price - open_trade.entry_price) * multiplier
            else:
                pnl = open_contracts_t1 * (open_trade.entry_price - exit_price) * multiplier
            capital_change += (
                pnl
                - self._transaction_cost(open_contracts_t1, tick_size)
                - self._exit_spread_cost(open_contracts_t1, tick_size, multiplier)
            )
            open_trade.pnl += pnl
            open_contracts_t1 = 0
            open_trade.stop_price = open_trade.entry_price
            targets_hit.append("target_1")

        if open_contracts_t2 > 0 and t2_touched:
            exit_price = open_trade.target_2
            if open_trade.direction == "long":
                pnl = open_contracts_t2 * (exit_price - open_trade.entry_price) * multiplier
            else:
                pnl = open_contracts_t2 * (open_trade.entry_price - exit_price) * multiplier
            capital_change += (
                pnl
                - self._transaction_cost(open_contracts_t2, tick_size)
                - self._exit_spread_cost(open_contracts_t2, tick_size, multiplier)
            )
            open_trade.pnl += pnl
            open_contracts_t2 = 0
            targets_hit.append("target_2")

        return open_contracts_t1, open_contracts_t2, capital_change, targets_hit

    def _check_stop_exit(
        self,
        open_trade: Trade,
        open_contracts_t1: int,
        open_contracts_t2: int,
        open_contracts_t3: int,
        multiplier: float,
        tick_size: float,
        stop_touched: bool,
        targets_hit: list,
        bar_open: Optional[float] = None,
    ) -> tuple[Optional[Trade], int, int, int, float, list]:
        """Check and process stop loss exit.

        When gap_stop_worst_fill=True and bar_open is provided, fills at the WORSE of
        (bar_open, stop_price) — modeling a gap that blows through the stop before the
        stop price itself is ever touchable. Default (bar_open=None or the flag unset)
        preserves the existing always-fill-at-stop_price behavior exactly.
        """
        if not stop_touched or (open_contracts_t1 + open_contracts_t2 + open_contracts_t3) <= 0:
            return (
                open_trade,
                open_contracts_t1,
                open_contracts_t2,
                open_contracts_t3,
                0.0,
                targets_hit,
            )

        remaining = open_contracts_t1 + open_contracts_t2 + open_contracts_t3
        exit_price = open_trade.stop_price
        if self.gap_stop_worst_fill and bar_open is not None:
            if open_trade.direction == "long":
                # Long stop: worse fill is the LOWER of (bar_open, stop_price) —
                # a gap-down open below the stop fills at the open, not the stop.
                exit_price = min(bar_open, open_trade.stop_price)
            else:
                # Short stop: worse fill is the HIGHER of (bar_open, stop_price).
                exit_price = max(bar_open, open_trade.stop_price)
        if open_trade.direction == "long":
            pnl = remaining * (exit_price - open_trade.entry_price) * multiplier
        else:
            pnl = remaining * (open_trade.entry_price - exit_price) * multiplier
        capital_change = (
            pnl
            - self._transaction_cost(remaining, tick_size)
            - self._exit_spread_cost(remaining, tick_size, multiplier)
        )
        open_trade.exit_price = exit_price
        open_trade.pnl += pnl
        open_trade.exit_reason = targets_hit[-1] if targets_hit else "stop"

        return None, 0, 0, 0, capital_change, targets_hit

    def _process_trailing_stop_long(
        self,
        open_trade: Trade,
        open_contracts: int,
        multiplier: float,
        tick_size: float,
        bar_atr: float,
        close: float,
        low: float,
    ) -> tuple[Optional[Trade], int, float, bool]:
        """Process trailing stop for long positions."""
        capital_change = 0.0
        exited = False

        favorable_excursion = close - open_trade.entry_price
        trail_active = self.strict_trailing or favorable_excursion >= 0.5 * bar_atr
        if trail_active:
            new_trail = close - self.trailing_atr_mult * bar_atr
            if new_trail > open_trade.stop_price:
                open_trade.stop_price = new_trail

            if low <= open_trade.stop_price:
                exit_price = open_trade.stop_price
                pnl = open_contracts * (exit_price - open_trade.entry_price) * multiplier
                capital_change = (
                    pnl
                    - self._transaction_cost(open_contracts, tick_size)
                    - self._exit_spread_cost(open_contracts, tick_size, multiplier)
                )
                open_trade.exit_price = exit_price
                open_trade.pnl += pnl
                open_trade.exit_reason = "trailing_stop"
                exited = True
                open_trade = None

        return open_trade, open_contracts, capital_change, exited

    def _process_trailing_stop_short(
        self,
        open_trade: Trade,
        open_contracts: int,
        multiplier: float,
        tick_size: float,
        bar_atr: float,
        close: float,
        high: float,
    ) -> tuple[Optional[Trade], int, float, bool]:
        """Process trailing stop for short positions."""
        capital_change = 0.0
        exited = False

        favorable_excursion = open_trade.entry_price - close
        if favorable_excursion >= 0.5 * bar_atr:
            new_trail = close + self.trailing_atr_mult * bar_atr
            if new_trail < open_trade.stop_price:
                open_trade.stop_price = new_trail

            if high >= open_trade.stop_price:
                exit_price = open_trade.stop_price
                pnl = open_contracts * (open_trade.entry_price - exit_price) * multiplier
                capital_change = (
                    pnl
                    - self._transaction_cost(open_contracts, tick_size)
                    - self._exit_spread_cost(open_contracts, tick_size, multiplier)
                )
                open_trade.exit_price = exit_price
                open_trade.pnl += pnl
                open_trade.exit_reason = "trailing_stop"
                exited = True
                open_trade = None

        return open_trade, open_contracts, capital_change, exited

    def _check_eod_close(
        self,
        open_trade: Trade,
        open_contracts_t1: int,
        open_contracts_t2: int,
        open_contracts_t3: int,
        multiplier: float,
        tick_size: float,
        is_eod: bool,
        close: float,
        idx,
        targets_hit: list,
    ) -> tuple[Optional[Trade], int, int, int, float, list]:
        """Check for end-of-day close."""
        if not is_eod:
            return (
                open_trade,
                open_contracts_t1,
                open_contracts_t2,
                open_contracts_t3,
                0.0,
                targets_hit,
            )

        remaining = open_contracts_t1 + open_contracts_t2 + open_contracts_t3
        if remaining <= 0:
            return (
                open_trade,
                open_contracts_t1,
                open_contracts_t2,
                open_contracts_t3,
                0.0,
                targets_hit,
            )

        if open_trade.direction == "long":
            pnl = remaining * (close - open_trade.entry_price) * multiplier
        else:
            pnl = remaining * (open_trade.entry_price - close) * multiplier
        capital_change = (
            pnl
            - self._transaction_cost(remaining, tick_size)
            - self._exit_spread_cost(remaining, tick_size, multiplier)
        )
        open_trade.pnl += pnl
        open_trade.exit_price = close
        open_trade.exit_date = idx
        open_trade.exit_reason = targets_hit[-1] if targets_hit else "eod"

        return None, 0, 0, 0, capital_change, targets_hit

    def _process_trade_on_bar(
        self,
        open_trade: Optional[Trade],
        open_contracts_t1: int,
        open_contracts_t2: int,
        open_contracts_t3: int,
        targets_hit: list,
        row: pd.Series,
        idx,
        df: pd.DataFrame,
        multiplier: float,
        tick_size: float,
        close: float,
    ) -> tuple[Optional[Trade], int, int, int, float, list, list]:
        """Process trade exits (targets, stops, trailing, EOD) on a single bar."""
        completed = []
        capital_change = 0.0

        if open_trade is None:
            return (
                None,
                open_contracts_t1,
                open_contracts_t2,
                open_contracts_t3,
                capital_change,
                targets_hit,
                completed,
            )

        open_trade.holding_bars += 1
        bar_open = row["open"]
        high = row["high"]
        low = row["low"]

        # Determine which levels are touched
        if open_trade.direction == "long":
            stop_touched = low <= open_trade.stop_price
            t1_touched = high >= open_trade.target_1 if open_contracts_t1 > 0 else False
            t2_touched = high >= open_trade.target_2 if open_contracts_t2 > 0 else False
            target_first = bar_open >= open_trade.entry_price
        else:
            stop_touched = high >= open_trade.stop_price
            t1_touched = low <= open_trade.target_1 if open_contracts_t1 > 0 else False
            t2_touched = low <= open_trade.target_2 if open_contracts_t2 > 0 else False
            target_first = bar_open <= open_trade.entry_price

        # Strict trailing: _process_trailing_stop_long updates trail BEFORE checking
        # (matching WFO's update-then-check order). Delegating stop here (prev-bar trail)
        # would exit 1 bar early vs WFO, causing missed re-entries.
        if self.trailing_stop and self.strict_trailing:
            stop_touched = False

        # Process exits in priority order
        both_stop_and_target = stop_touched and (t1_touched or t2_touched)
        # pessimistic_tie_breaker=True: on a genuine dual-touch bar, always assume the
        # stop was hit first (worst-case), overriding the bar_open-direction inference.
        if both_stop_and_target and self.pessimistic_tie_breaker:
            check_targets_first = False
        else:
            check_targets_first = both_stop_and_target and target_first

        if check_targets_first:
            open_contracts_t1, open_contracts_t2, capital_from_targets, new_targets = (
                self._check_targets_exit(
                    open_trade,
                    open_contracts_t1,
                    open_contracts_t2,
                    multiplier,
                    tick_size,
                    t1_touched,
                    t2_touched,
                )
            )
            capital_change += capital_from_targets
            targets_hit.extend(new_targets)
            if open_trade is not None:
                trade_before_stop = open_trade
                open_trade, new_t1, new_t2, new_t3, capital_from_stop, targets_hit = (
                    self._check_stop_exit(
                        open_trade,
                        open_contracts_t1,
                        open_contracts_t2,
                        open_contracts_t3,
                        multiplier,
                        tick_size,
                        stop_touched,
                        targets_hit,
                        bar_open,
                    )
                )
                if open_trade is None:
                    completed.append(trade_before_stop)
                open_contracts_t1, open_contracts_t2, open_contracts_t3 = new_t1, new_t2, new_t3
                capital_change += capital_from_stop
        else:
            trade_before_stop = open_trade
            open_trade, new_t1, new_t2, new_t3, capital_from_stop, targets_hit = (
                self._check_stop_exit(
                    open_trade,
                    open_contracts_t1,
                    open_contracts_t2,
                    open_contracts_t3,
                    multiplier,
                    tick_size,
                    stop_touched,
                    targets_hit,
                    bar_open,
                )
            )
            # Always credit stop PnL to capital, whether trade closed or not.
            # BUG (pre-2026-04-20): capital_from_stop was only added inside the "else" below,
            # so every stop-out loss was recorded on t.pnl but NEVER subtracted from capital.
            # Result: final_capital drifted wildly positive while sum(t.pnl) was deeply negative,
            # producing the observed "-$199K trade ledger alongside +$184K final capital" bug.
            capital_change += capital_from_stop
            if open_trade is None:
                completed.append(trade_before_stop)
            else:
                open_contracts_t1, open_contracts_t2, open_contracts_t3 = new_t1, new_t2, new_t3
                open_contracts_t1, open_contracts_t2, capital_from_targets, new_targets = (
                    self._check_targets_exit(
                        open_trade,
                        open_contracts_t1,
                        open_contracts_t2,
                        multiplier,
                        tick_size,
                        t1_touched,
                        t2_touched,
                    )
                )
                capital_change += capital_from_targets
                targets_hit.extend(new_targets)

        # Check all contracts exited via targets
        if (
            open_trade is not None
            and (open_contracts_t1 + open_contracts_t2 + open_contracts_t3) == 0
        ):
            open_trade.exit_reason = targets_hit[-1] if targets_hit else "target_1"
            open_trade.exit_price = close
            open_trade.exit_date = idx
            completed.append(open_trade)
            open_trade = None
            targets_hit = []

        return (
            open_trade,
            open_contracts_t1,
            open_contracts_t2,
            open_contracts_t3,
            capital_change,
            targets_hit,
            completed,
        )

    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
        multiplier: float = 1.0,
        commission_per_contract: Optional[float] = None,
        slippage_ticks: Optional[float] = None,
        spread_ticks: Optional[float] = None,
    ) -> BacktestResult:
        """
        Walk-forward simulation. df must have signals from generate_signals().
        Required columns: open, high, low, close, entry_signal, bias,
                         stop_level, target_1, target_2, target_3, regime
        """
        # Allow per-call overrides (takes precedence over config and __init__ defaults)
        if commission_per_contract is not None:
            self.commission_per_contract = commission_per_contract
        if slippage_ticks is not None:
            self.slippage_ticks = slippage_ticks
        if spread_ticks is not None:
            self.spread_ticks = spread_ticks

        tick_size = self._get_tick_size(symbol, multiplier)

        capital = self.initial_capital
        high_water_mark = capital
        completed_trades: List[Trade] = []
        equity_curve = [capital]

        open_trade: Optional[Trade] = None
        open_contracts_t1 = 0
        open_contracts_t2 = 0
        open_contracts_t3 = 0
        targets_hit: List[str] = []  # Track which targets were hit during trade

        daily_start_capital = capital
        current_date = None
        kill_switch = False

        # Bug 3 fix: pending entry to avoid look-ahead bias
        pending_entry: Optional[dict] = None

        for idx, row in df.iterrows():
            row_date = idx.date() if hasattr(idx, "date") else None

            # Reset daily tracking
            if row_date != current_date:
                current_date = row_date
                daily_start_capital = capital
                kill_switch = False

            # Check kill switch
            daily_pnl_pct = (capital - daily_start_capital) / daily_start_capital
            drawdown_pct = (capital - high_water_mark) / high_water_mark

            if daily_pnl_pct < -self.max_daily_loss or drawdown_pct < -self.max_drawdown:
                kill_switch = True

            # -- Execute pending entry from previous bar's signal (Bug 3 fix) --
            if pending_entry is not None and open_trade is None and not kill_switch:
                row_with_capital = row.copy()
                row_with_capital["capital"] = capital
                row_with_capital["symbol"] = symbol
                new_trade, t1c, t2c, t3c, targets_hit, capital_cost = self._process_pending_entry(
                    pending_entry, row_with_capital, idx, df, multiplier, tick_size
                )
                pending_entry = None
                if new_trade is not None:
                    open_trade = new_trade
                    open_contracts_t1 = t1c
                    open_contracts_t2 = t2c
                    open_contracts_t3 = t3c
                    targets_hit = []
                    capital -= capital_cost

            # -- Manage open trade (process exits on this bar) ---------
            close = row["close"]
            low = row.get("low", close)
            high = row.get("high", close)
            (
                open_trade,
                open_contracts_t1,
                open_contracts_t2,
                open_contracts_t3,
                capital_from_exits,
                targets_hit,
                closed_trades,
            ) = self._process_trade_on_bar(
                open_trade,
                open_contracts_t1,
                open_contracts_t2,
                open_contracts_t3,
                targets_hit,
                row,
                idx,
                df,
                multiplier,
                tick_size,
                close,
            )
            capital += capital_from_exits
            completed_trades.extend([t for t in closed_trades if t])

            # -- Trailing ATR stop logic ------------------------------------------
            if self.trailing_stop and open_trade is not None:
                remaining = open_contracts_t1 + open_contracts_t2 + open_contracts_t3
                t1_gate = (not self.trailing_post_t1) or ("target_1" in targets_hit)
                if remaining > 0 and t1_gate:
                    bar_atr = row.get("atr", 0)
                    if bar_atr > 0:
                        trade_before_trail = open_trade  # save ref before function sets it to None
                        ts_exited = False
                        if open_trade.direction == "long":
                            open_trade, open_contracts_t1, capital_ts, ts_exited = (
                                self._process_trailing_stop_long(
                                    open_trade,
                                    remaining,
                                    multiplier,
                                    tick_size,
                                    bar_atr,
                                    close,
                                    low,
                                )
                            )
                        else:
                            open_trade, open_contracts_t1, capital_ts, ts_exited = (
                                self._process_trailing_stop_short(
                                    open_trade,
                                    remaining,
                                    multiplier,
                                    tick_size,
                                    bar_atr,
                                    close,
                                    high,
                                )
                            )
                        capital += capital_ts
                        if ts_exited:
                            open_contracts_t2 = 0
                            open_contracts_t3 = 0
                            targets_hit = []
                            trade_before_trail.exit_date = idx
                            completed_trades.append(trade_before_trail)

            # End of day close
            remaining_contracts = open_contracts_t1 + open_contracts_t2 + open_contracts_t3
            if self.eod_close and remaining_contracts > 0 and open_trade is not None:
                next_idx_pos = df.index.get_loc(idx)
                is_last_bar = next_idx_pos == len(df) - 1
                is_eod = is_last_bar
                if not is_last_bar and hasattr(idx, "hour"):
                    next_bar_date = df.index[next_idx_pos + 1].date()
                    is_eod = next_bar_date != row_date

                trade_before_eod = open_trade
                (
                    open_trade,
                    open_contracts_t1,
                    open_contracts_t2,
                    open_contracts_t3,
                    capital_eod,
                    targets_hit,
                ) = self._check_eod_close(
                    open_trade,
                    open_contracts_t1,
                    open_contracts_t2,
                    open_contracts_t3,
                    multiplier,
                    tick_size,
                    is_eod,
                    close,
                    idx,
                    targets_hit,
                )
                capital += capital_eod
                if open_trade is None and capital_eod != 0.0:
                    completed_trades.append(trade_before_eod)

            # -- Explicit exit signal (e.g. death cross from SMA trend strategy) --
            if open_trade is not None:
                exit_sig = row.get("exit_signal", "NO_EXIT")
                if exit_sig == "EXIT_NOW":
                    remaining = open_contracts_t1 + open_contracts_t2 + open_contracts_t3
                    if remaining > 0:
                        if open_trade.direction == "long":
                            pnl = remaining * (close - open_trade.entry_price) * multiplier
                        else:
                            pnl = remaining * (open_trade.entry_price - close) * multiplier
                        capital_change = (
                            pnl
                            - self._transaction_cost(remaining, tick_size)
                            - self._exit_spread_cost(remaining, tick_size, multiplier)
                        )
                        capital += capital_change
                        open_trade.pnl += pnl
                        open_trade.exit_price = close
                        open_trade.exit_date = idx
                        open_trade.exit_reason = "exit_signal"
                        completed_trades.append(open_trade)
                        open_trade = None
                        open_contracts_t1 = open_contracts_t2 = open_contracts_t3 = 0

            # -- Check for new entry signal (Bug 3: store as pending, don't enter now) --
            if open_trade is None and pending_entry is None and not kill_switch:
                entry_sig = row.get("entry_signal", "NO_TRADE")
                bias = row.get("bias", "NEUTRAL")

                if entry_sig == "ENTRY_NOW" and bias not in ("NEUTRAL",):
                    direction = "long" if "BULL" in bias else "short"
                    signal_price = row["close"]
                    stop_price = row.get("stop_level", signal_price * 0.99)
                    target_1 = row.get("target_1", signal_price * 1.01)
                    target_2 = row.get("target_2", signal_price * 1.02)

                    # Compute ATR multiples for recalculation at actual entry
                    atr_val = row.get("atr", 1.0)
                    if atr_val <= 0:
                        atr_val = abs(signal_price - stop_price)
                    if atr_val <= 0:
                        continue

                    stop_dist = abs(signal_price - stop_price)
                    if stop_dist <= 0:
                        continue

                    # R:R pre-check on signal bar (Bug 6: lowered from 1.5 to 1.2)
                    rr = abs(target_1 - signal_price) / stop_dist
                    if rr < 1.2:
                        continue

                    pending_entry = {
                        "direction": direction,
                        "bias": bias,
                        "stop_atr_mult": stop_dist / atr_val,
                        "t1_atr_mult": abs(target_1 - signal_price) / atr_val,
                        "t2_atr_mult": abs(target_2 - signal_price) / atr_val,
                        "atr": atr_val,
                        "regime": row.get("regime", ""),
                    }

            # Update equity curve
            equity_curve.append(capital)
            if capital > high_water_mark:
                high_water_mark = capital

        # Compute total spread cost across all trades (entry half-spread + exit half-spread)
        cfg = _get_settings()
        if cfg.SPREAD_ENABLED:
            spread_cost_total = sum(
                t.contracts * self.spread_ticks * tick_size * multiplier * 2  # entry + exit
                for t in completed_trades
            )
        else:
            spread_cost_total = 0.0

        result = BacktestResult(
            symbol=symbol,
            start_date=str(df.index[0].date()) if len(df) > 0 else "",
            end_date=str(df.index[-1].date()) if len(df) > 0 else "",
            initial_capital=self.initial_capital,
            final_capital=capital,
            trades=completed_trades,
            equity_curve=equity_curve,
            total_bars=len(df),
            spread_cost_total=spread_cost_total,
        )

        return calculate_metrics(result)
