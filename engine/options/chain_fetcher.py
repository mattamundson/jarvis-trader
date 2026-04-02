"""
JARVIS Trader Options Engine — Chain Fetcher
Fetches real options chain data via yfinance, computes Greeks, and provides
delta-based filtering and IV Rank calculation.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy imports: yfinance is only required at runtime, not at import time.
# This prevents import errors in environments where yfinance is not installed.
try:
    import yfinance as yf

    _YFINANCE_AVAILABLE = True
except ImportError:
    _YFINANCE_AVAILABLE = False
    logger.warning("[chain_fetcher] yfinance not installed. Install with: pip install yfinance")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class OptionsContract:
    """Represents a single options contract from the chain."""

    strike: float
    expiry: date
    option_type: str  # "call" or "put"
    bid: float
    ask: float
    mid: float
    delta: float
    gamma: float
    theta: float
    vega: float
    iv: float  # implied volatility as decimal (e.g. 0.25)
    volume: int
    oi: int  # open interest
    in_the_money: bool = False
    last_price: float = 0.0

    @property
    def spread(self) -> float:
        """Bid-ask spread."""
        return round(self.ask - self.bid, 4)

    def __str__(self) -> str:
        return (
            f"{self.option_type.upper()} {self.strike} {self.expiry} | "
            f"mid={self.mid:.4f} IV={self.iv:.1%} "
            f"Δ={self.delta:+.4f} Γ={self.gamma:.4f} Θ={self.theta:.4f}"
        )


@dataclass
class OptionsChain:
    """Full options chain for one symbol and one expiry date."""

    symbol: str
    expiry: date
    underlying_price: float
    iv_rank: float  # 0–100
    calls: list[OptionsContract] = field(default_factory=list)
    puts: list[OptionsContract] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def total_contracts(self) -> int:
        return len(self.calls) + len(self.puts)

    def __str__(self) -> str:
        return (
            f"Chain: {self.symbol} expiry={self.expiry} "
            f"underlying={self.underlying_price:.2f} IVR={self.iv_rank:.1f} "
            f"calls={len(self.calls)} puts={len(self.puts)}"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_float(value, default: float = 0.0) -> float:
    """Convert a value to float safely, returning default on failure."""
    try:
        f = float(value)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_contract(
    row,
    strike: float,
    expiry: date,
    option_type: str,
    underlying_price: float,
    risk_free_rate: float = 0.05,
) -> OptionsContract:
    """Build an :class:`OptionsContract` from a yfinance chain row."""
    from .greeks_monitor import calculate_greeks

    bid = _safe_float(getattr(row, "bid", 0))
    ask = _safe_float(getattr(row, "ask", 0))
    mid = (
        round((bid + ask) / 2.0, 4)
        if (bid > 0 or ask > 0)
        else _safe_float(getattr(row, "lastPrice", 0))
    )
    iv = _safe_float(getattr(row, "impliedVolatility", 0))
    volume = _safe_int(getattr(row, "volume", 0))
    oi = _safe_int(getattr(row, "openInterest", 0))
    itm = bool(getattr(row, "inTheMoney", False))

    # Time to expiry in years
    today = datetime.utcnow().date()
    dte_days = max((expiry - today).days, 1)
    T = dte_days / 365.0

    # Calculate Greeks if IV is available
    greeks: dict[str, float] = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    if iv > 0 and underlying_price > 0 and T > 0:
        try:
            greeks = calculate_greeks(
                S=underlying_price,
                K=strike,
                T=T,
                r=risk_free_rate,
                sigma=iv,
                option_type=option_type,
            )
        except Exception as exc:
            logger.debug(
                "[chain_fetcher] Greeks calc failed for %s %.2f: %s", option_type, strike, exc
            )

    return OptionsContract(
        strike=strike,
        expiry=expiry,
        option_type=option_type,
        bid=bid,
        ask=ask,
        mid=mid,
        delta=greeks["delta"],
        gamma=greeks["gamma"],
        theta=greeks["theta"],
        vega=greeks["vega"],
        iv=iv,
        volume=volume,
        oi=oi,
        in_the_money=itm,
        last_price=_safe_float(getattr(row, "lastPrice", 0)),
    )


# ---------------------------------------------------------------------------
# Chain fetcher — yfinance
# ---------------------------------------------------------------------------


def fetch_chain_yfinance(
    symbol: str,
    expiry_dates: Optional[list[str]] = None,
    risk_free_rate: float = 0.05,
) -> Optional[OptionsChain]:
    """Fetch a live options chain from Yahoo Finance via yfinance.

    Args:
        symbol:       Yahoo Finance ticker (e.g. ``"SPY"``, ``"QQQ"``).
        expiry_dates: List of expiry date strings (``"YYYY-MM-DD"``).
                      If ``None``, uses the nearest available expiry.
        risk_free_rate: Annualised risk-free rate for Greeks calculation
                        (default 0.05 = 5 %).

    Returns:
        :class:`OptionsChain` with Greeks attached, or ``None`` on error.
    """
    if not _YFINANCE_AVAILABLE:
        logger.error("[chain_fetcher] yfinance is not installed.")
        return None

    try:
        ticker = yf.Ticker(symbol)
        spot_info = ticker.fast_info

        # Underlying price
        try:
            underlying_price = float(spot_info.last_price)
        except (AttributeError, TypeError):
            hist = ticker.history(period="1d")
            if hist.empty:
                logger.error("[chain_fetcher] Cannot determine underlying price for %s", symbol)
                return None
            underlying_price = float(hist["Close"].iloc[-1])

        # Available expiries
        available_expiries = ticker.options
        if not available_expiries:
            logger.error("[chain_fetcher] No options available for %s", symbol)
            return None

        if expiry_dates:
            target_expiry_str = expiry_dates[0]
        else:
            target_expiry_str = available_expiries[0]

        if target_expiry_str not in available_expiries:
            logger.warning(
                "[chain_fetcher] Expiry %s not found for %s. Using %s.",
                target_expiry_str,
                symbol,
                available_expiries[0],
            )
            target_expiry_str = available_expiries[0]

        expiry = date.fromisoformat(target_expiry_str)

        # Fetch the chain
        chain = ticker.option_chain(target_expiry_str)

        # Build calls
        calls: list[OptionsContract] = []
        for _, row in chain.calls.iterrows():
            strike = _safe_float(row.get("strike", 0))
            if strike <= 0:
                continue
            try:
                contract = _build_contract(
                    row, strike, expiry, "call", underlying_price, risk_free_rate
                )
                calls.append(contract)
            except Exception as exc:
                logger.debug("[chain_fetcher] Skipping call strike %.2f: %s", strike, exc)

        # Build puts
        puts: list[OptionsContract] = []
        for _, row in chain.puts.iterrows():
            strike = _safe_float(row.get("strike", 0))
            if strike <= 0:
                continue
            try:
                contract = _build_contract(
                    row, strike, expiry, "put", underlying_price, risk_free_rate
                )
                puts.append(contract)
            except Exception as exc:
                logger.debug("[chain_fetcher] Skipping put strike %.2f: %s", strike, exc)

        # Sort by strike
        calls.sort(key=lambda c: c.strike)
        puts.sort(key=lambda c: c.strike)

        ivr = get_iv_rank(symbol, days=252)

        options_chain = OptionsChain(
            symbol=symbol,
            expiry=expiry,
            underlying_price=underlying_price,
            iv_rank=ivr,
            calls=calls,
            puts=puts,
        )

        logger.info(
            "[chain_fetcher] %s | %d calls, %d puts | expiry=%s spot=%.2f IVR=%.1f",
            symbol,
            len(calls),
            len(puts),
            expiry,
            underlying_price,
            ivr,
        )
        return options_chain

    except Exception as exc:
        logger.exception("[chain_fetcher] fetch_chain_yfinance failed for %s: %s", symbol, exc)
        return None


# ---------------------------------------------------------------------------
# Filter utilities
# ---------------------------------------------------------------------------


def filter_by_delta(
    chain: OptionsChain,
    min_delta: float,
    max_delta: float,
    option_type: Optional[str] = None,
) -> list[OptionsContract]:
    """Filter contracts by absolute delta range.

    Args:
        chain:       :class:`OptionsChain` to filter.
        min_delta:   Minimum absolute delta (inclusive, e.g. 0.20).
        max_delta:   Maximum absolute delta (inclusive, e.g. 0.40).
        option_type: ``"call"``, ``"put"``, or ``None`` for both.

    Returns:
        Filtered list of :class:`OptionsContract` instances.
    """
    contracts: list[OptionsContract] = []

    if option_type in (None, "call"):
        contracts.extend(chain.calls)
    if option_type in (None, "put"):
        contracts.extend(chain.puts)

    return [c for c in contracts if min_delta <= abs(c.delta) <= max_delta]


def find_strike_by_delta(
    chain: OptionsChain,
    target_delta: float,
    option_type: str,
) -> Optional[OptionsContract]:
    """Find the contract closest to a target delta.

    Args:
        chain:        :class:`OptionsChain` to search.
        target_delta: Target absolute delta (e.g. 0.30).
        option_type:  ``"call"`` or ``"put"``.

    Returns:
        The :class:`OptionsContract` with delta closest to ``target_delta``,
        or ``None`` if no contracts are available.
    """
    source = chain.calls if option_type.lower() == "call" else chain.puts
    if not source:
        return None

    best = min(source, key=lambda c: abs(abs(c.delta) - target_delta))
    logger.debug(
        "[chain_fetcher] find_strike_by_delta target=%.2f → strike=%.2f delta=%.4f",
        target_delta,
        best.strike,
        best.delta,
    )
    return best


# ---------------------------------------------------------------------------
# IV Rank via yfinance historical options
# ---------------------------------------------------------------------------


def get_iv_rank(symbol: str, days: int = 252) -> float:
    """Calculate IV Rank for a symbol using historical options data.

    Pulls ``days`` trading days of historical close prices, derives a proxy
    daily IV from close-to-close returns (historical volatility), and
    computes IVR against the resulting 1-year range.

    The resulting IVR is an approximation — for true IVR you need a term
    structure database with daily ATM IV snapshots.

    Args:
        symbol: Yahoo Finance ticker symbol.
        days:   Look-back window in trading days (default 252 ≈ 1 year).

    Returns:
        IV Rank in [0, 100].  Returns 50.0 (neutral) on data failure.
    """
    if not _YFINANCE_AVAILABLE:
        return 50.0

    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1y")

        if len(hist) < 20:
            logger.warning("[chain_fetcher] Insufficient history for IVR calc on %s", symbol)
            return 50.0

        closes = hist["Close"].dropna()

        # Annualised historical volatility using a 21-day rolling window
        log_returns = closes.pct_change().dropna()
        rolling_vol = log_returns.rolling(21).std() * math.sqrt(252)
        rolling_vol = rolling_vol.dropna()

        if rolling_vol.empty:
            return 50.0

        current_iv = float(rolling_vol.iloc[-1])
        high_52w = float(rolling_vol.max())
        low_52w = float(rolling_vol.min())

        from .greeks_monitor import iv_rank

        ivr = iv_rank(current_iv, high_52w, low_52w)
        logger.debug(
            "[chain_fetcher] IVR %s: current=%.2%% high=%.2%% low=%.2%% → IVR=%.1f",
            symbol,
            current_iv,
            high_52w,
            low_52w,
            ivr,
        )
        return ivr

    except Exception as exc:
        logger.warning("[chain_fetcher] get_iv_rank failed for %s: %s", symbol, exc)
        return 50.0


# ---------------------------------------------------------------------------
# Multi-expiry fetch
# ---------------------------------------------------------------------------


def fetch_nearest_expiries(
    symbol: str,
    count: int = 3,
    risk_free_rate: float = 0.05,
) -> list[OptionsChain]:
    """Fetch chains for the nearest ``count`` expiries for a symbol.

    Args:
        symbol:         Yahoo Finance ticker.
        count:          Number of expiries to fetch (default 3).
        risk_free_rate: Risk-free rate for Greeks (default 0.05).

    Returns:
        List of :class:`OptionsChain` instances (may be shorter than ``count``
        if fewer expiries are available).
    """
    if not _YFINANCE_AVAILABLE:
        logger.error("[chain_fetcher] yfinance is not installed.")
        return []

    try:
        ticker = yf.Ticker(symbol)
        available = ticker.options[:count]
    except Exception as exc:
        logger.error("[chain_fetcher] Failed to fetch expiry list for %s: %s", symbol, exc)
        return []

    chains: list[OptionsChain] = []
    for expiry_str in available:
        chain = fetch_chain_yfinance(symbol, [expiry_str], risk_free_rate)
        if chain:
            chains.append(chain)

    return chains
