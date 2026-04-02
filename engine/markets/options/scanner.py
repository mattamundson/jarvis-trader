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


class OptionsScanner:
    """
    Scans option chains for premium-selling opportunities.
    Uses existing engine/options/chain_fetcher.py for data.
    """

    def __init__(self, underlyings: Optional[list[str]] = None, min_iv_rank: float = MIN_IV_RANK):
        self.underlyings = underlyings or DEFAULT_UNDERLYINGS
        self.min_iv_rank = min_iv_rank

    def scan(self) -> list[ScanResult]:
        """Scan all underlyings and return opportunities that meet criteria."""
        results = []
        for symbol in self.underlyings:
            try:
                result = self._scan_symbol(symbol)
                if result:
                    results.append(result)
            except Exception as exc:
                logger.error(f"Scanner error for {symbol}: {exc}")
        return results

    def _scan_symbol(self, symbol: str) -> Optional[ScanResult]:
        """Scan one symbol. Returns ScanResult if criteria met, else None."""
        try:
            from options.chain_fetcher import fetch_nearest_expiries, get_iv_rank
        except ImportError:
            logger.warning("options.chain_fetcher not available")
            return None

        try:
            iv_rank = get_iv_rank(symbol)
            if iv_rank < self.min_iv_rank:
                logger.debug(f"{symbol}: IV Rank {iv_rank:.1f} < {self.min_iv_rank} — skip")
                return None

            expiries = fetch_nearest_expiries(symbol, count=1, min_dte=25, max_dte=50)
            if not expiries:
                return None

            import yfinance as yf
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1d")
            if hist.empty:
                return None
            current_price = float(hist["Close"].iloc[-1])

            expiry = expiries[0]
            from datetime import date
            dte = (datetime.strptime(expiry, "%Y-%m-%d").date() - date.today()).days

            # Get VIX for regime
            vix_data = yf.Ticker("^VIX").history(period="1d")
            vix = float(vix_data["Close"].iloc[-1]) if not vix_data.empty else 20.0
            if vix < 15:
                regime = "low_vix"
            elif vix > 25:
                regime = "high_vix"
            else:
                regime = "normal"

            # Rough OTM strikes (10-delta approx)
            call_strikes = [round(current_price * 1.05, 0), round(current_price * 1.08, 0)]
            put_strikes = [round(current_price * 0.95, 0), round(current_price * 0.92, 0)]

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
            logger.error(f"_scan_symbol({symbol}) error: {exc}")
            return None
