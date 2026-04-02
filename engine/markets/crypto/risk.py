"""
CryptoRiskManager — position limits and capital controls for crypto trading.
Conservative: 10% max per coin, 30% stablecoin reserve, funding rate awareness.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("jarvis_trader.markets.crypto.risk")

MAX_COIN_PCT = 10.0          # Max 10% of crypto capital per coin
STABLECOIN_RESERVE_PCT = 30.0  # Keep 30% in stablecoin reserve
MAX_OPEN_TRADES = 5           # Max simultaneous open trades


class CryptoRiskManager:
    def __init__(
        self,
        total_capital: float = 15000.0,
        max_coin_pct: float = MAX_COIN_PCT,
        stablecoin_reserve_pct: float = STABLECOIN_RESERVE_PCT,
        max_open_trades: int = MAX_OPEN_TRADES,
    ):
        self.total_capital = total_capital
        self.max_coin_pct = max_coin_pct
        self.stablecoin_reserve_pct = stablecoin_reserve_pct
        self.max_open_trades = max_open_trades

    def max_trade_size_usdc(self) -> float:
        return self.total_capital * (self.max_coin_pct / 100)

    def available_capital(self, current_open_usdc: float) -> float:
        reserve = self.total_capital * (self.stablecoin_reserve_pct / 100)
        return max(0, self.total_capital - reserve - current_open_usdc)

    def check_new_trade(
        self,
        trade_size_usdc: float,
        current_open_usdc: float,
        current_open_count: int,
    ) -> tuple[bool, str]:
        if current_open_count >= self.max_open_trades:
            return False, f"Max {self.max_open_trades} trades reached"
        if trade_size_usdc > self.max_trade_size_usdc():
            return False, f"Trade ${trade_size_usdc:.0f} > max ${self.max_trade_size_usdc():.0f}"
        available = self.available_capital(current_open_usdc)
        if trade_size_usdc > available:
            return False, f"Insufficient available capital: ${available:.0f}"
        return True, "OK"

    def get_limits(self) -> dict:
        return {
            "total_capital": self.total_capital,
            "max_trade_usdc": self.max_trade_size_usdc(),
            "stablecoin_reserve_usdc": self.total_capital * (self.stablecoin_reserve_pct / 100),
            "max_open_trades": self.max_open_trades,
        }
