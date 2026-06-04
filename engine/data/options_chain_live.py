"""
JARVIS TRADER — Real-Time Options Chain Service (Phase 5.1)
==========================================================
Polls Interactive Brokers for live option chains, Greeks, and IV.
Supports defined-risk spread analysis for SPY, QQQ, and IWM.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ib_async import Option, Stock

from execution.ib_gateway_connector import IBGatewayConnector

logger = logging.getLogger("jarvis_trader.data.options")

@dataclass
class OptionStrike:
    strike: float
    right: str # 'C' | 'P'
    expiry: str
    bid: float
    ask: float
    mid: float
    delta: float
    gamma: float
    vega: float
    theta: float
    iv: float
    volume: int
    open_interest: int

class OptionsChainService:
    def __init__(self, ib_connector: IBGatewayConnector):
        self.ib = ib_connector
        self._cache: Dict[str, List[OptionStrike]] = {}
        self._last_update: Dict[str, datetime] = {}

    async def get_chain(
        self,
        symbol: str,
        min_dte: int = 7,
        max_dte: int = 45,
        strike_count: int = 10
    ) -> List[OptionStrike]:
        """
        Fetch the near-the-money option chain for a symbol.
        """
        if not self.ib or not self.ib.is_connected():
            logger.warning("[Options] IB not connected. Cannot fetch chain.")
            return []

        logger.info(f"[Options] Fetching chain for {symbol} (DTE: {min_dte}-{max_dte})...")

        try:
            # 1. Resolve Underlying
            underlying = Stock(symbol, 'SMART', 'USD')
            [underlying] = await self.ib._ib.qualifyContractsAsync(underlying)

            # 2. Get Expirations
            chains = await self.ib._ib.reqSecDefOptParamsAsync(
                underlying.symbol, '', underlying.secType, underlying.conId
            )

            if not chains:
                return []

            # Use SMART chain
            chain = next(c for c in chains if c.exchange == 'SMART')
            expirations = sorted(chain.expirations)

            # Filter by DTE
            now = datetime.now(timezone.utc)
            valid_expiries = []
            for exp in expirations:
                exp_dt = datetime.strptime(exp, '%Y%m%d').replace(tzinfo=timezone.utc)
                dte = (exp_dt - now).days
                if min_dte <= dte <= max_dte:
                    valid_expiries.append(exp)

            if not valid_expiries:
                return []

            target_expiry = valid_expiries[0] # Focus on nearest valid expiry

            # 3. Request Market Price of Underlying
            [ticker] = await self.ib._ib.reqTickersAsync(underlying)
            underlying_price = ticker.marketPrice()
            if underlying_price != underlying_price: # NaN check
                underlying_price = ticker.close

            # 4. Filter Strikes
            strikes = sorted(chain.strikes)
            # Find strikes closest to price
            atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - underlying_price))
            start_idx = max(0, atm_idx - strike_count)
            end_idx = min(len(strikes), atm_idx + strike_count)
            target_strikes = strikes[start_idx:end_idx]

            # 5. Build Option Contracts
            contracts = []
            for strike in target_strikes:
                for right in ['C', 'P']:
                    contracts.append(Option(symbol, target_expiry, strike, right, 'SMART'))

            contracts = await self.ib._ib.qualifyContractsAsync(*contracts)

            # 6. Request Tickers (Greeks)
            tickers = await self.ib._ib.reqTickersAsync(*contracts)

            results = []
            for t in tickers:
                greeks = t.modelGreeks
                if not greeks:
                    continue

                results.append(OptionStrike(
                    strike=t.contract.strike,
                    right=t.contract.right,
                    expiry=t.contract.lastTradeDateOrContractMonth,
                    bid=t.bid,
                    ask=t.ask,
                    mid=(t.bid + t.ask) / 2 if (t.bid > 0 and t.ask > 0) else 0.0,
                    delta=greeks.delta,
                    gamma=greeks.gamma,
                    vega=greeks.vega,
                    theta=greeks.theta,
                    iv=greeks.impliedVol,
                    volume=t.volume,
                    open_interest=0 # reqTickers doesn't always provide OI
                ))

            self._cache[symbol] = results
            self._last_update[symbol] = datetime.now()

            return results

        except Exception as e:
            logger.error(f"[Options] Failed to fetch chain for {symbol}: {e}")
            return []

    def get_cached_chain(self, symbol: str) -> Optional[List[OptionStrike]]:
        return self._cache.get(symbol)
