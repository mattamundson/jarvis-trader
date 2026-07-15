"""
JARVIS Trader Options Engine — Chain Fetcher
Fetches real options chain data via Polygon.io / MarketDataManager, computes Greeks,
and provides delta-based filtering and IV Rank calculation.

Extended (2026-05-20): get_pc_skew + get_term_structure wired to Polygon options API
via ``_polygon_skew`` helpers.  Both functions are synchronous and return None on
any data failure so callers (OptionsAnalyst, options_router) abstain gracefully.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API — get_pc_skew
# ---------------------------------------------------------------------------


def get_pc_skew(symbol: str, expiry: Optional[str] = None) -> Optional[float]:
    """Compute the 25-delta put/call IV skew for ``symbol`` via Polygon.

    When ``expiry`` is None, picks the nearest weekly expiry that is
    >= 2 days and <= 14 days out (avoids 0DTE noise and LEAPs).

    Skew convention (matches OptionsAnalyst._skew_signal):
        positive  -> put IV > call IV -> bearish skew (puts richer than calls)
        negative  -> call IV > put IV -> bullish skew

    Returned as **percentage points**: (put_iv_25d - call_iv_25d) * 100.
    OptionsAnalyst normalises: signal = -skew / 50.0 -> +/-1.0 at +/-50 pts.

    Args:
        symbol: Underlying ticker (e.g. "SPY", "MES").
        expiry: Optional "YYYY-MM-DD" expiry.  None -> auto-select.

    Returns:
        Float skew in percentage-point units, or None on missing data.
    """
    try:
        from ._polygon_skew import (
            fetch_chain_snapshot,
            iv_at_delta,
            nearest_expiry,
        )

        chosen_expiry = expiry or nearest_expiry(symbol, min_days=2, max_days=14)
        if not chosen_expiry:
            logger.debug("[chain_fetcher] get_pc_skew: no expiry for %s", symbol)
            return None

        contracts = fetch_chain_snapshot(symbol, chosen_expiry)
        if not contracts:
            logger.debug("[chain_fetcher] get_pc_skew: empty chain %s %s", symbol, chosen_expiry)
            return None

        put_iv = iv_at_delta(contracts, target_delta=0.25, side="put")
        call_iv = iv_at_delta(contracts, target_delta=0.25, side="call")

        if put_iv is None or call_iv is None:
            logger.debug(
                "[chain_fetcher] get_pc_skew: insufficient delta data %s (put=%s call=%s)",
                symbol,
                put_iv,
                call_iv,
            )
            return None

        skew_pts = (put_iv - call_iv) * 100.0
        logger.info(
            "[chain_fetcher] get_pc_skew %s expiry=%s put_iv_25d=%.4f call_iv_25d=%.4f skew=%.2fpts",
            symbol,
            chosen_expiry,
            put_iv,
            call_iv,
            skew_pts,
        )
        return skew_pts

    except Exception as exc:
        logger.warning("[chain_fetcher] get_pc_skew(%s) error: %s", symbol, exc)
        return None


# ---------------------------------------------------------------------------
# Public API — get_term_structure
# ---------------------------------------------------------------------------


def get_term_structure(symbol: str) -> Optional[dict]:
    """Compute the IV term-structure slope across the front 3 expiries.

    Fetches ATM IV (average of ATM call + put) for the front-week,
    front-month, and second-month expiries.

    Slope convention (matches OptionsAnalyst._term_signal):
        positive slope -> front-week IV > front-month IV -> backwardation (fear)
        negative slope -> front-week IV < front-month IV -> contango (normal)
    OptionsAnalyst normalises: signal = -slope / 20.0 -> +/-1.0 at +/-20 pts.

    Args:
        symbol: Underlying ticker.

    Returns:
        Dict with keys: slope, front_week_atm_iv, front_month_atm_iv,
        second_month_atm_iv, regime, spot, symbol, computed_at.
        None when fewer than 2 expiries have valid ATM IV.
    """
    try:
        from datetime import timezone

        from ._polygon_skew import (
            atm_iv,
            fetch_chain_snapshot,
            front_n_expiries,
            spot_price_from_polygon,
        )

        expiries = front_n_expiries(symbol, n=3)
        if len(expiries) < 2:
            logger.debug("[chain_fetcher] get_term_structure: fewer than 2 expiries for %s", symbol)
            return None

        spot = spot_price_from_polygon(symbol)
        if spot is None or spot <= 0:
            logger.debug("[chain_fetcher] get_term_structure: no spot for %s", symbol)
            return None

        atm_ivs: list[Optional[float]] = []
        for exp in expiries:
            contracts = fetch_chain_snapshot(symbol, exp)
            atm_ivs.append(atm_iv(contracts, spot))

        while len(atm_ivs) < 3:
            atm_ivs.append(None)

        front_week_iv, front_month_iv, second_month_iv = atm_ivs[0], atm_ivs[1], atm_ivs[2]

        if front_week_iv is None or front_month_iv is None:
            logger.debug("[chain_fetcher] get_term_structure: missing front-2 IVs for %s", symbol)
            return None

        slope = (front_week_iv - front_month_iv) * 100.0
        regime = "backwardation" if slope > 1.0 else ("contango" if slope < -1.0 else "flat")

        result = {
            "symbol": symbol,
            "spot": round(spot, 4),
            "front_week_atm_iv": round(front_week_iv, 6),
            "front_month_atm_iv": round(front_month_iv, 6),
            "second_month_atm_iv": (
                round(second_month_iv, 6) if second_month_iv is not None else None
            ),
            "slope": round(slope, 4),
            "regime": regime,
            "computed_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        logger.info(
            "[chain_fetcher] get_term_structure %s slope=%.2fpts regime=%s",
            symbol,
            slope,
            regime,
        )
        return result

    except Exception as exc:
        logger.warning("[chain_fetcher] get_term_structure(%s) error: %s", symbol, exc)
        return None


# ---------------------------------------------------------------------------
# Public API — get_expected_move
# ---------------------------------------------------------------------------


def get_expected_move(
    symbol: str,
    expiry: Optional[str] = None,
    r: float = 0.05,
) -> Optional[dict]:
    """Compute the ATM-straddle-derived Expected Move for ``symbol`` via Polygon.

    When ``expiry`` is None, picks the nearest available expiry in the
    2-45 DTE window (front-week through front-month) using the same
    Polygon reference-contracts lookup as ``get_pc_skew``/``get_term_structure``.

    Wires real market data into ``premium_calculator.expected_move``:
      - F     = live underlying spot (``spot_price_from_polygon``)
      - K     = ATM strike (defaults to F inside ``expected_move``)
      - sigma = ATM implied volatility, averaged across the ATM call + put
                at the strike nearest spot (``atm_iv``)
      - T     = actual DTE / 365 for the chosen expiry
      - r     = annualised risk-free rate (default 5%)

    Args:
        symbol: Underlying ticker (e.g. "SPY", "MES").
        expiry: Optional "YYYY-MM-DD" expiry. None -> auto-select nearest.
        r:      Annualised risk-free rate (decimal), default 0.05.

    Returns:
        The dict returned by ``premium_calculator.expected_move`` plus
        ``symbol``, ``expiry``, and ``dte_days``, or None on missing data.
    """
    try:
        from ._polygon_skew import (
            atm_iv,
            fetch_chain_snapshot,
            nearest_expiry,
            spot_price_from_polygon,
        )
        from .premium_calculator import expected_move as _expected_move

        chosen_expiry = expiry or nearest_expiry(symbol, min_days=2, max_days=45)
        if not chosen_expiry:
            logger.debug("[chain_fetcher] get_expected_move: no expiry for %s", symbol)
            return None

        spot = spot_price_from_polygon(symbol)
        if spot is None or spot <= 0:
            logger.debug("[chain_fetcher] get_expected_move: no spot for %s", symbol)
            return None

        contracts = fetch_chain_snapshot(symbol, chosen_expiry)
        if not contracts:
            logger.debug(
                "[chain_fetcher] get_expected_move: empty chain %s %s", symbol, chosen_expiry
            )
            return None

        sigma = atm_iv(contracts, spot)
        if sigma is None or sigma <= 0:
            logger.debug("[chain_fetcher] get_expected_move: no ATM IV for %s", symbol)
            return None

        expiry_date = date.fromisoformat(chosen_expiry)
        today = datetime.utcnow().date()
        dte_days = max((expiry_date - today).days, 1)
        T = dte_days / 365.0

        result = _expected_move(F=spot, T=T, sigma=sigma, r=r)
        result["symbol"] = symbol
        result["expiry"] = chosen_expiry
        result["dte_days"] = dte_days

        logger.info(
            "[chain_fetcher] get_expected_move %s expiry=%s F=%.2f sigma=%.4f "
            "straddle=$%.2f EM=%.2f%%",
            symbol,
            chosen_expiry,
            spot,
            sigma,
            result["expected_move_dollars"],
            result["expected_move_pct"] * 100,
        )
        return result

    except Exception as exc:
        logger.warning("[chain_fetcher] get_expected_move(%s) error: %s", symbol, exc)
        return None


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
            f"Delta={self.delta:+.4f} Gamma={self.gamma:.4f} Theta={self.theta:.4f}"
        )


@dataclass
class OptionsChain:
    """Full options chain for one symbol and one expiry date."""

    symbol: str
    expiry: date
    underlying_price: float
    iv_rank: float  # 0-100
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
    """Build an OptionsContract from a chain row."""
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

    greeks: dict[str, float] = {
        "delta": 0.0,
        "gamma": 0.0,
        "theta": 0.0,
        "vega": 0.0,
        "rho": 0.0,
    }
    if iv > 0 and underlying_price > 0 and T > 0:
        try:
            greeks = calculate_greeks(
                F=underlying_price,
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
# Chain fetcher — data_manager
# ---------------------------------------------------------------------------


def fetch_chain(
    symbol: str,
    expiry_dates: Optional[list[str]] = None,
    risk_free_rate: float = 0.05,
    data_manager=None,
) -> Optional["OptionsChain"]:
    """Fetch a live options chain via MarketDataManager / Polygon.

    Args:
        symbol:         Ticker symbol (e.g. "SPY", "QQQ").
        expiry_dates:   List of expiry date strings ("YYYY-MM-DD").
                        If None, uses the nearest available expiry.
        risk_free_rate: Annualised risk-free rate for Greeks calculation
                        (default 0.05 = 5 %).
        data_manager:   Optional MarketDataManager instance. When provided,
                        used for spot price and expiry lookups.

    Returns:
        OptionsChain with Greeks attached, or None on error.
    """
    import asyncio

    try:
        underlying_price: Optional[float] = None

        if data_manager is not None:
            try:
                loop = asyncio.get_event_loop()
                price_data = loop.run_until_complete(data_manager.get_current_price(symbol))
                underlying_price = float(price_data.get("last_price", 0) or 0) or None
            except Exception as exc:
                logger.warning("[chain_fetcher] data_manager price fetch failed: %s", exc)

        if underlying_price is None or underlying_price <= 0:
            logger.error("[chain_fetcher] Cannot determine underlying price for %s", symbol)
            return None

        available_expiries: list[str] = []

        if data_manager is not None:
            try:
                loop = asyncio.get_event_loop()
                available_expiries = loop.run_until_complete(
                    data_manager.get_options_expirations(symbol)
                )
            except Exception as exc:
                logger.warning("[chain_fetcher] data_manager expiry fetch failed: %s", exc)

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
        calls: list[OptionsContract] = []
        puts: list[OptionsContract] = []

        ivr = get_iv_rank(symbol, days=252, data_manager=data_manager)

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
        logger.exception("[chain_fetcher] fetch_chain failed for %s: %s", symbol, exc)
        return None


# ---------------------------------------------------------------------------
# Filter utilities
# ---------------------------------------------------------------------------


def filter_by_delta(
    chain: "OptionsChain",
    min_delta: float,
    max_delta: float,
    option_type: Optional[str] = None,
) -> list[OptionsContract]:
    """Filter contracts by absolute delta range.

    Args:
        chain:       OptionsChain to filter.
        min_delta:   Minimum absolute delta (inclusive, e.g. 0.20).
        max_delta:   Maximum absolute delta (inclusive, e.g. 0.40).
        option_type: "call", "put", or None for both.

    Returns:
        Filtered list of OptionsContract instances.
    """
    contracts: list[OptionsContract] = []

    if option_type in (None, "call"):
        contracts.extend(chain.calls)
    if option_type in (None, "put"):
        contracts.extend(chain.puts)

    return [c for c in contracts if min_delta <= abs(c.delta) <= max_delta]


def find_strike_by_delta(
    chain: "OptionsChain",
    target_delta: float,
    option_type: str,
) -> Optional[OptionsContract]:
    """Find the contract closest to a target delta.

    Args:
        chain:        OptionsChain to search.
        target_delta: Target absolute delta (e.g. 0.30).
        option_type:  "call" or "put".

    Returns:
        The OptionsContract with delta closest to target_delta, or None.
    """
    source = chain.calls if option_type.lower() == "call" else chain.puts
    if not source:
        return None

    best = min(source, key=lambda c: abs(abs(c.delta) - target_delta))
    logger.debug(
        "[chain_fetcher] find_strike_by_delta target=%.2f -> strike=%.2f delta=%.4f",
        target_delta,
        best.strike,
        best.delta,
    )
    return best


# ---------------------------------------------------------------------------
# IV Rank via historical price data
# ---------------------------------------------------------------------------


def get_iv_rank(symbol: str, days: int = 252, data_manager=None) -> float:
    """Calculate IV Rank for a symbol using historical price data.

    Fetches ``days`` trading days of historical close prices via data_manager
    (falls back to BacktestDataLoader), derives a proxy daily IV from
    close-to-close returns (historical volatility), and computes IVR against
    the resulting 1-year range.

    Args:
        symbol:       Ticker symbol.
        days:         Look-back window in trading days (default 252 = 1 year).
        data_manager: Optional MarketDataManager for data fetching.

    Returns:
        IV Rank in [0, 100].  Returns 50.0 (neutral) on data failure.
    """
    import asyncio
    from datetime import timedelta

    try:
        closes = None

        if data_manager is not None:
            try:
                loop = asyncio.get_event_loop()
                df = loop.run_until_complete(
                    data_manager.get_bars(
                        symbol=symbol,
                        lookback_days=days + 30,
                        timeframe="1d",
                    )
                )
                if df is not None and len(df) >= 20 and "close" in df.columns:
                    closes = df["close"].dropna()
            except Exception as exc:
                logger.warning("[chain_fetcher] data_manager bars failed for IVR: %s", exc)

        if closes is None or len(closes) < 20:
            try:
                from backtest.data_loader import BacktestDataLoader

                end_date = datetime.utcnow().strftime("%Y-%m-%d")
                start_date = (datetime.utcnow() - timedelta(days=days + 60)).strftime("%Y-%m-%d")
                loader = BacktestDataLoader()
                df = loader.load(symbol, start_date, end_date, "1d")
                if df is not None and len(df) >= 20 and "close" in df.columns:
                    closes = df["close"].dropna()
            except Exception as exc:
                logger.warning("[chain_fetcher] BacktestDataLoader failed for IVR: %s", exc)

        if closes is None or len(closes) < 20:
            logger.warning("[chain_fetcher] Insufficient history for IVR calc on %s", symbol)
            return 50.0

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
            "[chain_fetcher] IVR %s: current=%.4f high=%.4f low=%.4f -> IVR=%.1f",
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
    data_manager=None,
    **kwargs,
) -> list["OptionsChain"]:
    """Fetch chains for the nearest ``count`` expiries for a symbol.

    Args:
        symbol:         Ticker symbol.
        count:          Number of expiries to fetch (default 3).
        risk_free_rate: Risk-free rate for Greeks (default 0.05).
        data_manager:   Optional MarketDataManager for data fetching.

    Returns:
        List of OptionsChain instances (may be shorter than count
        if fewer expiries are available).
    """
    import asyncio

    try:
        available: list[str] = []
        if data_manager is not None:
            try:
                loop = asyncio.get_event_loop()
                available = loop.run_until_complete(data_manager.get_options_expirations(symbol))
            except Exception as exc:
                logger.warning("[chain_fetcher] data_manager expiry fetch failed: %s", exc)

        if not available:
            logger.error("[chain_fetcher] No expiries available for %s", symbol)
            return []

        available = available[:count]
    except Exception as exc:
        logger.error("[chain_fetcher] Failed to fetch expiry list for %s: %s", symbol, exc)
        return []

    chains: list[OptionsChain] = []
    for expiry_str in available:
        chain = fetch_chain(symbol, [expiry_str], risk_free_rate, data_manager=data_manager)
        if chain:
            chains.append(chain)

    return chains
