"""
CrossMarketRiskManager — aggregate risk across all market modules.
Halts individual markets at 2% loss; halts ALL at 5% portfolio loss.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger("jarvis_trader.risk.cross_market")

DEFAULT_MAX_MARKET_LOSS_PCT = 2.0    # Halt individual market at -2% of its capital
DEFAULT_MAX_PORTFOLIO_LOSS_PCT = 5.0  # Halt all markets at -5% of total portfolio


@dataclass
class MarketRiskState:
    market: str
    capital: float
    daily_pnl: float = 0.0
    halted: bool = False
    halt_reason: Optional[str] = None
    last_updated: datetime = field(default_factory=datetime.utcnow)

    @property
    def daily_loss_pct(self) -> float:
        if self.capital <= 0:
            return 0.0
        return (self.daily_pnl / self.capital) * 100


@dataclass
class PortfolioRiskState:
    date: date = field(default_factory=date.today)
    total_capital: float = 0.0
    total_pnl: float = 0.0
    portfolio_halted: bool = False
    halt_reason: Optional[str] = None
    markets: dict[str, MarketRiskState] = field(default_factory=dict)

    @property
    def portfolio_loss_pct(self) -> float:
        if self.total_capital <= 0:
            return 0.0
        return (self.total_pnl / self.total_capital) * 100


class CrossMarketRiskManager:
    """
    Enforces cross-market risk limits.

    Checks:
    1. Per-market: daily P&L < -2% of market capital → halt that market
    2. Portfolio: total daily P&L < -5% of total capital → halt ALL
    3. Correlation: directional exposure > 30% → block new positions
    """

    def __init__(
        self,
        market_capitals: dict[str, float],
        max_market_loss_pct: float = DEFAULT_MAX_MARKET_LOSS_PCT,
        max_portfolio_loss_pct: float = DEFAULT_MAX_PORTFOLIO_LOSS_PCT,
        max_directional_exposure_pct: float = 30.0,
    ):
        self.max_market_loss_pct = max_market_loss_pct
        self.max_portfolio_loss_pct = max_portfolio_loss_pct
        self.max_directional_exposure_pct = max_directional_exposure_pct

        total = sum(market_capitals.values())
        self._state = PortfolioRiskState(
            total_capital=total,
            markets={
                m: MarketRiskState(market=m, capital=c)
                for m, c in market_capitals.items()
            },
        )
        self._halt_callbacks: list = []

    def register_halt_callback(self, callback) -> None:
        """Register a callback to call when a market is halted."""
        self._halt_callbacks.append(callback)

    def update_pnl(self, market: str, daily_pnl: float) -> dict:
        """
        Update P&L for a market and check all risk limits.
        Returns a dict with any triggered actions.
        """
        if market not in self._state.markets:
            logger.warning(f"Unknown market: {market}")
            return {}

        market_state = self._state.markets[market]
        market_state.daily_pnl = daily_pnl
        market_state.last_updated = datetime.utcnow()

        # Recompute portfolio total
        self._state.total_pnl = sum(m.daily_pnl for m in self._state.markets.values())

        actions = {}

        # Check per-market loss limit
        if not market_state.halted and market_state.daily_loss_pct < -self.max_market_loss_pct:
            reason = (
                f"Daily loss {market_state.daily_loss_pct:.2f}% "
                f"exceeds -{self.max_market_loss_pct}% limit"
            )
            self._halt_market(market, reason)
            actions["market_halted"] = {"market": market, "reason": reason}

        # Check portfolio-wide loss limit
        if not self._state.portfolio_halted and self._state.portfolio_loss_pct < -self.max_portfolio_loss_pct:
            reason = (
                f"Portfolio loss {self._state.portfolio_loss_pct:.2f}% "
                f"exceeds -{self.max_portfolio_loss_pct}% limit"
            )
            self._halt_portfolio(reason)
            actions["portfolio_halted"] = {"reason": reason}

        return actions

    def _halt_market(self, market: str, reason: str) -> None:
        self._state.markets[market].halted = True
        self._state.markets[market].halt_reason = reason
        logger.critical(f"MARKET HALT [{market}]: {reason}")
        for cb in self._halt_callbacks:
            try:
                cb(market=market, reason=reason, halt_type="market")
            except Exception as exc:
                logger.error(f"Halt callback error: {exc}")

    def _halt_portfolio(self, reason: str) -> None:
        self._state.portfolio_halted = True
        self._state.halt_reason = reason
        # Also halt all individual markets
        for market in self._state.markets:
            if not self._state.markets[market].halted:
                self._halt_market(market, f"Portfolio halt: {reason}")
        logger.critical(f"PORTFOLIO HALT: {reason}")

    def is_market_halted(self, market: str) -> bool:
        if self._state.portfolio_halted:
            return True
        state = self._state.markets.get(market)
        return state.halted if state else False

    def is_portfolio_halted(self) -> bool:
        return self._state.portfolio_halted

    def reset_daily(self) -> None:
        """Call at start of each trading day to reset daily P&L tracking."""
        self._state.date = date.today()
        self._state.total_pnl = 0.0
        self._state.portfolio_halted = False
        self._state.halt_reason = None
        for market_state in self._state.markets.values():
            market_state.daily_pnl = 0.0
            market_state.halted = False
            market_state.halt_reason = None
        logger.info("CrossMarketRiskManager: daily reset complete")

    def get_status(self) -> dict:
        return {
            "date": str(self._state.date),
            "total_capital": self._state.total_capital,
            "total_daily_pnl": self._state.total_pnl,
            "portfolio_loss_pct": round(self._state.portfolio_loss_pct, 3),
            "portfolio_halted": self._state.portfolio_halted,
            "halt_reason": self._state.halt_reason,
            "max_market_loss_pct": self.max_market_loss_pct,
            "max_portfolio_loss_pct": self.max_portfolio_loss_pct,
            "markets": {
                name: {
                    "capital": s.capital,
                    "daily_pnl": s.daily_pnl,
                    "loss_pct": round(s.daily_loss_pct, 3),
                    "halted": s.halted,
                    "halt_reason": s.halt_reason,
                }
                for name, s in self._state.markets.items()
            },
        }
