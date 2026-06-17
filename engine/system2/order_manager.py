"""
System 2 — Order Manager
========================
Manages the lifecycle of a single ES or NQ position:

Entry → Initial Stop → T1 (50% exit, stop → BE) → T2 (50% exit) → flat
                     → Backstop: 8 bars without T1 → full market exit

State machine per position:
  PENDING_ENTRY → OPEN_FULL → OPEN_HALF (T1 hit) → FLAT
                            → BACKSTOP_EXIT (8-bar timeout)

Position sizing: 1% risk of $50k account = $500 per trade
  - ES: $500 / (stop_pts × $50/pt) = contracts
  - NQ: $500 / (stop_pts × $20/pt) = contracts
  - Min 1 contract, max 5 contracts (hard cap for paper testing)

Order types submitted to IBKR:
  Entry:   MarketOrder (at close of signal bar — MOC or immediate MKT)
  Stop:    StopOrder (initial 0.75×ATR stop, updates to BE after T1)
  T1:      LimitOrder (0.80×ATR, 50% of position)
  T2:      LimitOrder (2.00×ATR, remaining 50%)
  Backstop: MarketOrder (cancel all open orders, submit MKT for remainder)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Optional, Callable, Coroutine

logger = logging.getLogger(__name__)


# ── Contract specs ────────────────────────────────────────────────────────────
_CONTRACT_SPECS: dict[str, dict] = {
    "ES": {"tick": 0.25, "tick_value": 12.50, "multiplier": 50.0},
    "NQ": {"tick": 0.25, "tick_value":  5.00, "multiplier": 20.0},
}

# Risk parameters
_ACCOUNT_SIZE_USD    = 50_000.0
_RISK_PCT_PER_TRADE  = 0.01       # 1%
_MAX_CONTRACTS       = 5          # hard cap per instrument
_MIN_CONTRACTS       = 1
_BACKSTOP_BARS       = 8          # exit full position if T1 not hit in 8 bars
_COMMISSION_RT_USD   = 4.50       # round-trip commission per contract
_SLIPPAGE_TICKS      = 1          # 1-tick slippage on each fill


# ── Position state machine ────────────────────────────────────────────────────
class PositionState(Enum):
    PENDING_ENTRY    = auto()   # Signal fired, waiting for entry fill
    OPEN_FULL        = auto()   # Fully entered, stop + T1 + T2 working
    OPEN_HALF        = auto()   # T1 hit: 50% exited, stop moved to BE, T2 working
    BACKSTOP_EXIT    = auto()   # 8-bar timeout triggered, exiting
    FLAT             = auto()   # All positions closed


@dataclass
class PositionOrders:
    """IBKR order IDs for live tracking."""
    entry_order_id:  Optional[int] = None
    stop_order_id:   Optional[int] = None
    t1_order_id:     Optional[int] = None
    t2_order_id:     Optional[int] = None
    backstop_order_id: Optional[int] = None


@dataclass
class PositionRecord:
    """
    Full state for one System 2 position.
    Created when a signal fires, updated on each bar tick.
    """
    symbol: str
    direction: str           # "LONG" (only mode for now)
    entry_price: float
    stop_price: float
    t1_price: float
    t2_price: float
    be_price: float          # breakeven = entry + 1 tick (after T1 hit)
    atr: float
    total_contracts: int
    t1_contracts: int        # half of total (rounded down)
    t2_contracts: int        # remainder
    signal_bar_time: datetime
    state: PositionState = PositionState.PENDING_ENTRY
    bars_open: int = 0
    t1_hit: bool = False
    t2_hit: bool = False
    entry_fill_price: Optional[float] = None
    orders: PositionOrders = field(default_factory=PositionOrders)
    pnl_usd: float = 0.0
    closed_at: Optional[datetime] = None
    close_reason: str = ""

    def tick_price(self, symbol: str) -> float:
        return _CONTRACT_SPECS[symbol]["tick"]

    def point_value(self, symbol: str) -> float:
        return _CONTRACT_SPECS[symbol]["multiplier"]

    def pnl_from_price(self, exit_price: float, contracts: int) -> float:
        """Calculate PnL for a partial/full exit."""
        pts = exit_price - self.entry_price  # long only
        gross = pts * self.point_value(self.symbol) * contracts
        comm  = _COMMISSION_RT_USD * contracts
        slip  = _SLIPPAGE_TICKS * self.tick_price(self.symbol) * self.point_value(self.symbol) * contracts
        return gross - comm - slip


def _size_position(symbol: str, stop_price: float, entry_price: float) -> int:
    """
    Size position by 1% risk.
    stop_pts = entry - stop (long only)
    contracts = floor(risk_usd / (stop_pts × multiplier))
    """
    stop_pts = abs(entry_price - stop_price)
    if stop_pts <= 0:
        logger.warning(f"[{symbol}] Stop pts = 0, defaulting to min contracts")
        return _MIN_CONTRACTS

    mult = _CONTRACT_SPECS[symbol]["multiplier"]
    risk_usd = _ACCOUNT_SIZE_USD * _RISK_PCT_PER_TRADE
    raw = risk_usd / (stop_pts * mult)
    contracts = max(_MIN_CONTRACTS, min(_MAX_CONTRACTS, int(raw)))
    logger.info(
        f"[{symbol}] Sizing: risk=${risk_usd:.0f}, stop_pts={stop_pts:.2f}, "
        f"mult={mult}, raw={raw:.2f} → {contracts} contracts"
    )
    return contracts


# ── Order Manager ─────────────────────────────────────────────────────────────
class System2OrderManager:
    """
    Manages open positions and their associated IBKR orders for System 2.

    This class is the bridge between:
      - System2SignalMonitor  (fires System2Signal events)
      - IBKRExecutor          (submits actual orders via ib_async)

    All order submission is async. The executor loop calls on_bar() each time
    a new 1h bar closes to advance the state machine (backstop check).

    Parameters
    ----------
    ibkr_executor   : IBKRExecutor instance (from engine/execution/ibkr_executor.py)
    paper           : bool — paper mode (port 4002), used for logging
    on_position_closed : optional async callback when a position closes
    """

    def __init__(
        self,
        ibkr_executor=None,
        paper: bool = True,
        on_position_closed: Optional[Callable[[PositionRecord], Coroutine]] = None,
    ):
        self.ibkr = ibkr_executor
        self.paper = paper
        self.on_position_closed = on_position_closed
        # Active positions keyed by symbol (one position per symbol at a time)
        self._positions: dict[str, PositionRecord] = {}

    # ── Signal → Entry ────────────────────────────────────────────────────────
    async def on_signal(self, signal) -> Optional[PositionRecord]:
        """
        Called by signal monitor when a setup completes.
        Sizes position, submits entry + bracket orders.
        Returns PositionRecord or None on failure.
        """
        from system2.signal_monitor import System2Signal
        sym = signal.symbol

        # Don't stack positions on same symbol
        if sym in self._positions and self._positions[sym].state not in (
            PositionState.FLAT,
        ):
            logger.warning(
                f"[{sym}] Signal fired but position already open "
                f"(state={self._positions[sym].state}), ignoring"
            )
            return None

        contracts = _size_position(sym, signal.stop_price, signal.entry_price)
        t1_contracts = max(1, contracts // 2)
        t2_contracts = contracts - t1_contracts

        # Breakeven = entry + 1 tick
        tick = _CONTRACT_SPECS[sym]["tick"]
        be_price = round(signal.entry_price + tick, 2)

        pos = PositionRecord(
            symbol           = sym,
            direction        = "LONG",
            entry_price      = signal.entry_price,
            stop_price       = signal.stop_price,
            t1_price         = signal.t1_price,
            t2_price         = signal.t2_price,
            be_price         = be_price,
            atr              = signal.atr,
            total_contracts  = contracts,
            t1_contracts     = t1_contracts,
            t2_contracts     = t2_contracts,
            signal_bar_time  = signal.bar_time,
        )

        logger.info(
            f"[{sym}] New position: {contracts} contracts | "
            f"Entry={pos.entry_price:.2f}  Stop={pos.stop_price:.2f}  "
            f"T1={pos.t1_price:.2f} ({t1_contracts}ct)  "
            f"T2={pos.t2_price:.2f} ({t2_contracts}ct)  BE={pos.be_price:.2f}"
        )

        self._positions[sym] = pos

        # Submit orders (or log if IBKR not connected)
        await self._submit_entry_bracket(pos)
        return pos

    async def _submit_entry_bracket(self, pos: PositionRecord):
        """Submit entry MKT + stop + T1 limit + T2 limit as bracket."""
        sym = pos.symbol

        if self.ibkr is None:
            logger.warning(
                f"[{sym}] No IBKR executor attached — logging orders only (dry run)"
            )
            pos.state = PositionState.OPEN_FULL  # assume filled for state machine
            logger.info(
                f"[DRY RUN] {sym} ENTRY MKT {pos.total_contracts}ct @ ~{pos.entry_price:.2f}"
            )
            logger.info(
                f"[DRY RUN] {sym} STOP {pos.total_contracts}ct @ {pos.stop_price:.2f}"
            )
            logger.info(
                f"[DRY RUN] {sym} T1 LIMIT {pos.t1_contracts}ct @ {pos.t1_price:.2f}"
            )
            logger.info(
                f"[DRY RUN] {sym} T2 LIMIT {pos.t2_contracts}ct @ {pos.t2_price:.2f}"
            )
            return

        try:
            # Entry: Market order for full position
            entry_req = {
                "symbol":     sym,
                "action":     "BUY",
                "quantity":   pos.total_contracts,
                "order_type": "MKT",
                "paper":      self.paper,
            }
            entry_result = await self.ibkr.submit_order(entry_req)
            pos.orders.entry_order_id = getattr(entry_result, "order_id", None)
            pos.state = PositionState.OPEN_FULL
            logger.info(f"[{sym}] Entry submitted: {entry_result}")

            # Stop: protect full position
            stop_req = {
                "symbol":     sym,
                "action":     "SELL",
                "quantity":   pos.total_contracts,
                "order_type": "STP",
                "stop_price": pos.stop_price,
                "paper":      self.paper,
            }
            stop_result = await self.ibkr.submit_order(stop_req)
            pos.orders.stop_order_id = getattr(stop_result, "order_id", None)

            # T1 limit: partial exit (50%)
            t1_req = {
                "symbol":      sym,
                "action":      "SELL",
                "quantity":    pos.t1_contracts,
                "order_type":  "LMT",
                "limit_price": pos.t1_price,
                "paper":       self.paper,
            }
            t1_result = await self.ibkr.submit_order(t1_req)
            pos.orders.t1_order_id = getattr(t1_result, "order_id", None)

            # T2 limit: remaining exit
            t2_req = {
                "symbol":      sym,
                "action":      "SELL",
                "quantity":    pos.t2_contracts,
                "order_type":  "LMT",
                "limit_price": pos.t2_price,
                "paper":       self.paper,
            }
            t2_result = await self.ibkr.submit_order(t2_req)
            pos.orders.t2_order_id = getattr(t2_result, "order_id", None)

            logger.info(
                f"[{sym}] Bracket submitted: "
                f"stop={pos.orders.stop_order_id} "
                f"t1={pos.orders.t1_order_id} "
                f"t2={pos.orders.t2_order_id}"
            )

        except Exception as e:
            logger.error(f"[{sym}] Order submission failed: {e}", exc_info=True)

    # ── Bar tick: advance state machine ──────────────────────────────────────
    async def on_bar(self, symbol: str, bar: dict):
        """
        Called each time a new 1h bar closes for a monitored symbol.
        Advances the state machine: backstop check, T1/T2 fill simulation.

        bar: dict with at minimum 'high', 'low', 'close', 'timestamp'
        """
        if symbol not in self._positions:
            return

        pos = self._positions[symbol]
        if pos.state in (PositionState.FLAT, PositionState.BACKSTOP_EXIT):
            return

        pos.bars_open += 1
        high  = float(bar.get("high",  0))
        low   = float(bar.get("low",   0))
        close = float(bar.get("close", 0))
        ts    = bar.get("timestamp", datetime.now(timezone.utc))

        # ── Stop hit ─────────────────────────────────────────────────────────
        current_stop = pos.be_price if pos.t1_hit else pos.stop_price
        if low <= current_stop:
            remaining = pos.t2_contracts if pos.t1_hit else pos.total_contracts
            pnl = pos.pnl_from_price(current_stop, remaining)
            pos.pnl_usd += pnl
            logger.info(
                f"[{symbol}] STOP HIT @ {current_stop:.2f} | "
                f"{remaining}ct | PnL=${pnl:.2f} | bars_open={pos.bars_open}"
            )
            await self._close_position(pos, current_stop, "STOP", ts)
            return

        # ── T1 target check ───────────────────────────────────────────────────
        if pos.state == PositionState.OPEN_FULL and not pos.t1_hit:
            if high >= pos.t1_price:
                pos.t1_hit = True
                pos.state  = PositionState.OPEN_HALF
                pnl_t1 = pos.pnl_from_price(pos.t1_price, pos.t1_contracts)
                pos.pnl_usd += pnl_t1
                logger.info(
                    f"[{symbol}] T1 HIT @ {pos.t1_price:.2f} | "
                    f"{pos.t1_contracts}ct exited | PnL=${pnl_t1:.2f} | "
                    f"Stop → BE {pos.be_price:.2f}"
                )
                # Move stop to breakeven on IBKR
                await self._move_stop_to_be(pos)

        # ── T2 target check ───────────────────────────────────────────────────
        if pos.state == PositionState.OPEN_HALF and pos.t1_hit:
            if high >= pos.t2_price:
                pnl_t2 = pos.pnl_from_price(pos.t2_price, pos.t2_contracts)
                pos.pnl_usd += pnl_t2
                logger.info(
                    f"[{symbol}] T2 HIT @ {pos.t2_price:.2f} | "
                    f"{pos.t2_contracts}ct exited | PnL=${pnl_t2:.2f}"
                )
                await self._close_position(pos, pos.t2_price, "T2", ts)
                return

        # ── Backstop: 8 bars without T1 ──────────────────────────────────────
        if (
            pos.state == PositionState.OPEN_FULL
            and not pos.t1_hit
            and pos.bars_open >= _BACKSTOP_BARS
        ):
            logger.info(
                f"[{symbol}] BACKSTOP triggered: {pos.bars_open} bars, "
                f"T1 never hit | exiting full {pos.total_contracts}ct @ market"
            )
            pnl = pos.pnl_from_price(close, pos.total_contracts)
            pos.pnl_usd += pnl
            await self._close_position(pos, close, "BACKSTOP", ts)

    async def _move_stop_to_be(self, pos: PositionRecord):
        """Update the stop order to breakeven after T1 hit."""
        if self.ibkr is None:
            logger.info(
                f"[DRY RUN] {pos.symbol} STOP updated to BE {pos.be_price:.2f}"
            )
            return

        try:
            # Cancel existing stop, replace with BE stop
            if pos.orders.stop_order_id:
                await self.ibkr.cancel_order(pos.orders.stop_order_id)

            be_req = {
                "symbol":     pos.symbol,
                "action":     "SELL",
                "quantity":   pos.t2_contracts,
                "order_type": "STP",
                "stop_price": pos.be_price,
                "paper":      self.paper,
            }
            result = await self.ibkr.submit_order(be_req)
            pos.orders.stop_order_id = getattr(result, "order_id", None)
            logger.info(
                f"[{pos.symbol}] BE stop placed @ {pos.be_price:.2f} "
                f"(order_id={pos.orders.stop_order_id})"
            )
        except Exception as e:
            logger.error(f"[{pos.symbol}] BE stop update failed: {e}", exc_info=True)

    async def _close_position(
        self,
        pos: PositionRecord,
        exit_price: float,
        reason: str,
        ts: datetime,
    ):
        """Cancel all open orders and mark position flat."""
        pos.state      = PositionState.FLAT
        pos.closed_at  = ts
        pos.close_reason = reason

        # Cancel any remaining working orders on IBKR
        if self.ibkr is not None:
            for oid in [
                pos.orders.stop_order_id,
                pos.orders.t1_order_id,
                pos.orders.t2_order_id,
                pos.orders.backstop_order_id,
            ]:
                if oid:
                    try:
                        await self.ibkr.cancel_order(oid)
                    except Exception:
                        pass
        else:
            logger.info(
                f"[DRY RUN] {pos.symbol} position FLAT | "
                f"reason={reason} | total_pnl=${pos.pnl_usd:.2f}"
            )

        logger.info(
            f"[{pos.symbol}] Position closed | reason={reason} | "
            f"exit={exit_price:.2f} | bars_open={pos.bars_open} | "
            f"total_pnl=${pos.pnl_usd:.2f}"
        )

        del self._positions[pos.symbol]

        if self.on_position_closed:
            await self.on_position_closed(pos)

    # ── Status ────────────────────────────────────────────────────────────────
    def active_positions(self) -> dict[str, PositionRecord]:
        return dict(self._positions)

    def position_summary(self) -> str:
        if not self._positions:
            return "No active positions"
        lines = []
        for sym, pos in self._positions.items():
            lines.append(
                f"{sym}: {pos.state.name} | {pos.total_contracts}ct | "
                f"entry={pos.entry_price:.2f} stop={pos.stop_price:.2f} | "
                f"bars_open={pos.bars_open} | pnl=${pos.pnl_usd:.2f}"
            )
        return "\n".join(lines)
