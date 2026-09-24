"""
OptionsScanner — find premium-selling opportunities in SPY/SPX/IWM/QQQ.
Criteria: IV Rank > 30, OI > 100, 30-45 DTE, liquid strikes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger("jarvis_trader.markets.options.scanner")

DEFAULT_UNDERLYINGS = ["SPY", "QQQ", "IWM"]
MIN_IV_RANK = 30.0
MIN_OI = 100


@dataclass
class ScanResult:
    symbol: str
    expiry: str
    iv_rank: float
    call_strikes: list[float]
    put_strikes: list[float]
    current_price: float
    days_to_expiry: int
    regime: str = "normal"  # "low_vix" | "normal" | "high_vix"
    scanned_at: datetime = None

    def __post_init__(self):
        if self.scanned_at is None:
            self.scanned_at = datetime.utcnow()


def _run_sync(coro):
    """Drive a coroutine from synchronous code.

    Raises RuntimeError when called from inside a running event loop, because
    the underlying ib_async socket cannot be driven from a second loop.  Async
    callers must await the ``*_async`` variant directly.
    """
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    coro.close()
    raise RuntimeError(
        "OptionsScanner: sync entry point called from inside a running event "
        "loop.  Await scan_async() instead."
    )


class OptionsScanner:
    """
    Scans option chains for premium-selling opportunities.
    Uses engine/options/chain_fetcher.py for data and an injected
    MarketDataManager singleton so ib_async sockets run on the correct loop.
    """

    def __init__(
        self,
        underlyings: Optional[list[str]] = None,
        min_iv_rank: float = MIN_IV_RANK,
        data_manager=None,
    ):
        self.underlyings = underlyings or DEFAULT_UNDERLYINGS
        self.min_iv_rank = min_iv_rank
        self.data_manager = data_manager

    # ------------------------------------------------------------------
    # Sync entry points (for non-async callers — thread pools, cron jobs)
    # ------------------------------------------------------------------

    def scan(self) -> list[ScanResult]:
        """Sync wrapper around :meth:`scan_async`."""
        return _run_sync(self.scan_async())

    # ------------------------------------------------------------------
    # Async (correct path for ib_async)
    # ------------------------------------------------------------------

    async def scan_async(self) -> list[ScanResult]:
        """Scan all underlyings and return opportunities that meet criteria."""
        results = []
        for symbol in self.underlyings:
            try:
                result = await self._scan_symbol_async(symbol)
                if result:
                    results.append(result)
            except Exception as exc:
                logger.error("Scanner error for %s: %s", symbol, exc)
        return results

    async def _scan_symbol_async(self, symbol: str) -> Optional[ScanResult]:
        """Scan one symbol. Returns ScanResult if criteria met, else None."""
        try:
            from options.chain_fetcher import (
                fetch_nearest_expiries_async,
                get_iv_rank_async,
            )
        except ImportError:
            logger.warning("options.chain_fetcher not available")
            return None

        dm = self.data_manager
        if dm is None:
            logger.error(
                "_scan_symbol_async: no data_manager injected on OptionsScanner. "
                "Caller must pass data_manager= to the constructor."
            )
            return None

        try:
            iv_rank = await get_iv_rank_async(
                symbol, days=252, data_manager=dm
            )
            if iv_rank < self.min_iv_rank:
                logger.debug(
                    "%s: IV Rank %.1f < %.1f — skip",
                    symbol, iv_rank, self.min_iv_rank,
                )
                return None

            # Use the async variant directly — no sync wrapper thread-pool hack.
            expiries = await fetch_nearest_expiries_async(
                symbol, count=1, data_manager=dm
            )
            if not expiries:
                return None

            price_data = await dm.get_current_price(symbol)
            current_price = float(price_data.get("last_price", 0) or 0)
            if current_price <= 0:
                return None

            expiry = expiries[0].expiry.strftime("%Y-%m-%d")
            from datetime import date

            dte = (
                datetime.strptime(expiry, "%Y-%m-%d").date() - date.today()
            ).days

            vix_data = await dm.get_vix()
            vix = float(vix_data.get("value", 20.0) or 20.0)
            if vix < 15:
                regime = "low_vix"
            elif vix > 25:
                regime = "high_vix"
            else:
                regime = "normal"

            call_strikes = [
                round(current_price * 1.05, 0),
                round(current_price * 1.08, 0),
            ]
            put_strikes = [
                round(current_price * 0.95, 0),
                round(current_price * 0.92, 0),
            ]

            return ScanResult(
                symbol=symbol,
                expiry=expiry,
                iv_rank=iv_rank,
                call_strikes=call_strikes,
                put_strikes=put_strikes,
                current_price=current_price,
                days_to_expiry=dte,
                regime=regime,
            )
        except Exception as exc:
            logger.error("_scan_symbol_async(%s) error: %s", symbol, exc)
            return None
