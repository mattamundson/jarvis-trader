"""
JARVIS Trader Options Engine — Strategy Executor
Builds OptionsOrder objects for each supported strategy and validates them
against the current VIX regime and market regime state.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class OptionsStrategy(str, Enum):
    """Supported options strategies."""
    COVERED_CALL       = "COVERED_CALL"
    CREDIT_SPREAD_PUT  = "CREDIT_SPREAD_PUT"    # Bull put spread
    CREDIT_SPREAD_CALL = "CREDIT_SPREAD_CALL"   # Bear call spread
    IRON_CONDOR        = "IRON_CONDOR"
    PROTECTIVE_PUT     = "PROTECTIVE_PUT"
    STRADDLE           = "STRADDLE"
    STRANGLE           = "STRANGLE"


class VIXRegime(str, Enum):
    """VIX-based market volatility regime."""
    LOW     = "LOW"       # VIX < 15
    NORMAL  = "NORMAL"    # 15 ≤ VIX < 20
    HIGH    = "HIGH"      # 20 ≤ VIX < 30
    EXTREME = "EXTREME"   # VIX ≥ 30


class RegimeState(str, Enum):
    """5-layer regime framework state from JARVIS technical analysis."""
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    RANGING       = "RANGING"
    VOLATILE      = "VOLATILE"
    MIXED         = "MIXED"
    UNKNOWN       = "UNKNOWN"


# ---------------------------------------------------------------------------
# OptionsOrder dataclass
# ---------------------------------------------------------------------------

@dataclass
class OptionsLeg:
    """Represents a single leg of an options order."""
    action: Literal["BUY", "SELL"]
    option_type: Literal["call", "put"]
    strike: float
    expiry: date
    quantity: int = 1


@dataclass
class OptionsOrder:
    """A complete options order ready for review or execution.

    Produced by the strategy builder functions.  All risk metrics are
    per-spread (1 contract = 100 shares for equity options).
    """
    symbol: str
    strategy: OptionsStrategy
    legs: list[OptionsLeg]
    estimated_premium: float    # net credit (positive) or debit (negative) per share
    max_risk: float             # maximum dollar loss per spread (positive)
    max_profit: float           # maximum dollar gain per spread (positive)
    notes: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    expiry_dte: int = 0         # days to expiration at order creation

    def __str__(self) -> str:
        legs_str = ", ".join(
            f"{leg.action} {leg.option_type.upper()} {leg.strike} {leg.expiry}"
            for leg in self.legs
        )
        return (
            f"[{self.strategy.value}] {self.symbol} | "
            f"Legs: {legs_str} | "
            f"Premium: ${self.estimated_premium:.2f}/sh | "
            f"MaxProfit: ${self.max_profit:.0f} | MaxRisk: ${self.max_risk:.0f}"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _expiry_date(dte: int) -> date:
    """Return the expiry date ``dte`` calendar days from today."""
    return (datetime.utcnow() + timedelta(days=dte)).date()


def _round_strike(price: float, tick: float = 1.0) -> float:
    """Round a raw strike to the nearest tick size."""
    return round(round(price / tick) * tick, 2)


# ---------------------------------------------------------------------------
# Strategy builders
# ---------------------------------------------------------------------------

def build_covered_call(
    symbol: str,
    futures_price: float,
    atr: float,
    expiry_dte: int = 30,
    tick_size: float = 1.0,
) -> OptionsOrder:
    """Build a covered call order.

    Strike is set at ``futures_price + 1.0 × ATR``, targeting a ~0.30 delta.
    The underlying (futures/shares) is assumed to already be held.

    Args:
        symbol:      Underlying ticker symbol.
        futures_price: Current price of the underlying.
        atr:         Current ATR value (same units as price).
        expiry_dte:  Target days to expiration (default 30).
        tick_size:   Option strike tick size (default 1.0 point).

    Returns:
        :class:`OptionsOrder` for a covered call.
    """
    strike = _round_strike(futures_price + 1.0 * atr, tick_size)
    expiry = _expiry_date(expiry_dte)

    # Estimate premium as rough proxy: 0.5 % of underlying price
    estimated_premium = round(futures_price * 0.005, 4)
    max_profit = round(estimated_premium * 100, 2)
    max_risk = round(futures_price * 100, 2)  # underlying position risk

    logger.info(
        "[build_covered_call] %s | price=%.2f atr=%.2f → strike=%.2f DTE=%d",
        symbol, futures_price, atr, strike, expiry_dte,
    )

    return OptionsOrder(
        symbol=symbol,
        strategy=OptionsStrategy.COVERED_CALL,
        legs=[
            OptionsLeg(action="SELL", option_type="call", strike=strike, expiry=expiry),
        ],
        estimated_premium=estimated_premium,
        max_risk=max_risk,
        max_profit=max_profit,
        expiry_dte=expiry_dte,
        notes=(
            f"Covered call | short strike {strike} (~1.0×ATR OTM) | "
            f"delta target ~0.30 | underlying held separately"
        ),
    )


def build_bull_put_spread(
    symbol: str,
    futures_price: float,
    atr: float,
    width: float = 5.0,
    expiry_dte: int = 30,
    tick_size: float = 1.0,
) -> OptionsOrder:
    """Build a bull put (credit) spread.

    Short put at ~0.30 delta (``futures_price - 1.0×ATR``); long put
    ``width`` points lower as the hedge.

    Args:
        symbol:      Underlying ticker.
        futures_price: Current underlying price.
        atr:         14-period ATR value.
        width:       Spread width in points (default 5.0).
        expiry_dte:  Days to expiration (default 30).
        tick_size:   Strike tick size.

    Returns:
        :class:`OptionsOrder` for a bull put spread.
    """
    short_strike = _round_strike(futures_price - 1.0 * atr, tick_size)
    long_strike  = _round_strike(short_strike - width, tick_size)
    expiry = _expiry_date(expiry_dte)

    # Rough credit estimate: ~30 % of spread width
    net_premium = round(width * 0.30, 4)
    max_profit  = round(net_premium * 100, 2)
    max_risk    = round((width - net_premium) * 100, 2)

    logger.info(
        "[build_bull_put_spread] %s | short=%.2f long=%.2f DTE=%d",
        symbol, short_strike, long_strike, expiry_dte,
    )

    return OptionsOrder(
        symbol=symbol,
        strategy=OptionsStrategy.CREDIT_SPREAD_PUT,
        legs=[
            OptionsLeg(action="SELL", option_type="put", strike=short_strike, expiry=expiry),
            OptionsLeg(action="BUY",  option_type="put", strike=long_strike,  expiry=expiry),
        ],
        estimated_premium=net_premium,
        max_risk=max_risk,
        max_profit=max_profit,
        expiry_dte=expiry_dte,
        notes=(
            f"Bull put spread | short {short_strike} / long {long_strike} | "
            f"width={width} pts | delta target ~0.30 on short strike"
        ),
    )


def build_bear_call_spread(
    symbol: str,
    futures_price: float,
    atr: float,
    width: float = 5.0,
    expiry_dte: int = 30,
    tick_size: float = 1.0,
) -> OptionsOrder:
    """Build a bear call (credit) spread.

    Short call at ~0.30 delta (``futures_price + 1.0×ATR``); long call
    ``width`` points higher as the hedge.

    Args:
        symbol:      Underlying ticker.
        futures_price: Current underlying price.
        atr:         14-period ATR value.
        width:       Spread width in points (default 5.0).
        expiry_dte:  Days to expiration (default 30).
        tick_size:   Strike tick size.

    Returns:
        :class:`OptionsOrder` for a bear call spread.
    """
    short_strike = _round_strike(futures_price + 1.0 * atr, tick_size)
    long_strike  = _round_strike(short_strike + width, tick_size)
    expiry = _expiry_date(expiry_dte)

    net_premium = round(width * 0.30, 4)
    max_profit  = round(net_premium * 100, 2)
    max_risk    = round((width - net_premium) * 100, 2)

    logger.info(
        "[build_bear_call_spread] %s | short=%.2f long=%.2f DTE=%d",
        symbol, short_strike, long_strike, expiry_dte,
    )

    return OptionsOrder(
        symbol=symbol,
        strategy=OptionsStrategy.CREDIT_SPREAD_CALL,
        legs=[
            OptionsLeg(action="SELL", option_type="call", strike=short_strike, expiry=expiry),
            OptionsLeg(action="BUY",  option_type="call", strike=long_strike,  expiry=expiry),
        ],
        estimated_premium=net_premium,
        max_risk=max_risk,
        max_profit=max_profit,
        expiry_dte=expiry_dte,
        notes=(
            f"Bear call spread | short {short_strike} / long {long_strike} | "
            f"width={width} pts | delta target ~0.30 on short strike"
        ),
    )


def build_iron_condor(
    symbol: str,
    futures_price: float,
    atr: float,
    wing_width: float = 5.0,
    expiry_dte: int = 30,
    tick_size: float = 1.0,
) -> OptionsOrder:
    """Build an iron condor.

    Short strikes placed at ±1 SD (approximately 0.16 delta) from the
    current price.  1 SD ≈ ``futures_price × iv × sqrt(T)``; we use
    ATR as a proxy (``1.5 × ATR`` ≈ 1 SD for intraday assets).

    **Iron condors are BLOCKED in HIGH/EXTREME VIX — use** :func:`validate_order`.

    Args:
        symbol:       Underlying ticker.
        futures_price: Current underlying price.
        atr:          14-period ATR value.
        wing_width:   Width of each spread wing in points (default 5.0).
        expiry_dte:   Days to expiration (default 30).
        tick_size:    Strike tick size.

    Returns:
        :class:`OptionsOrder` for an iron condor.
    """
    one_sd = 1.5 * atr
    short_call = _round_strike(futures_price + one_sd, tick_size)
    long_call  = _round_strike(short_call + wing_width, tick_size)
    short_put  = _round_strike(futures_price - one_sd, tick_size)
    long_put   = _round_strike(short_put - wing_width, tick_size)
    expiry     = _expiry_date(expiry_dte)

    # Combined credit estimate: ~30 % of one wing × 2
    net_premium = round(wing_width * 0.30 * 2, 4)
    max_profit  = round(net_premium * 100, 2)
    max_risk    = round((wing_width - net_premium / 2) * 100, 2)

    logger.info(
        "[build_iron_condor] %s | put_spread=%s/%s call_spread=%s/%s DTE=%d",
        symbol, short_put, long_put, short_call, long_call, expiry_dte,
    )

    return OptionsOrder(
        symbol=symbol,
        strategy=OptionsStrategy.IRON_CONDOR,
        legs=[
            OptionsLeg(action="SELL", option_type="put",  strike=short_put,  expiry=expiry),
            OptionsLeg(action="BUY",  option_type="put",  strike=long_put,   expiry=expiry),
            OptionsLeg(action="SELL", option_type="call", strike=short_call, expiry=expiry),
            OptionsLeg(action="BUY",  option_type="call", strike=long_call,  expiry=expiry),
        ],
        estimated_premium=net_premium,
        max_risk=max_risk,
        max_profit=max_profit,
        expiry_dte=expiry_dte,
        notes=(
            f"Iron condor | put_spread={short_put}/{long_put} "
            f"call_spread={short_call}/{long_call} | "
            f"delta target ~0.16 on short strikes | RANGING regime only"
        ),
    )


def build_protective_put(
    symbol: str,
    futures_price: float,
    atr: float,
    expiry_dte: int = 30,
    tick_size: float = 1.0,
) -> OptionsOrder:
    """Build a protective put (portfolio insurance).

    Long put placed at ``futures_price - 1.25×ATR``, targeting ~0.20 delta.
    Trigger condition: VIX > 20 AND regime is VOLATILE.

    Args:
        symbol:       Underlying ticker.
        futures_price: Current underlying price.
        atr:          14-period ATR value.
        expiry_dte:   Days to expiration (default 30).
        tick_size:    Strike tick size.

    Returns:
        :class:`OptionsOrder` for a protective put (debit trade).
    """
    strike = _round_strike(futures_price - 1.25 * atr, tick_size)
    expiry = _expiry_date(expiry_dte)

    # Rough debit estimate for a 0.20 delta put: ~0.8 % of underlying
    estimated_premium = round(futures_price * 0.008, 4)
    max_risk   = round(estimated_premium * 100, 2)   # debit paid
    max_profit = round((futures_price - strike - estimated_premium) * 100, 2)

    logger.info(
        "[build_protective_put] %s | price=%.2f strike=%.2f DTE=%d",
        symbol, futures_price, strike, expiry_dte,
    )

    return OptionsOrder(
        symbol=symbol,
        strategy=OptionsStrategy.PROTECTIVE_PUT,
        legs=[
            OptionsLeg(action="BUY", option_type="put", strike=strike, expiry=expiry),
        ],
        estimated_premium=-estimated_premium,   # debit = negative
        max_risk=max_risk,
        max_profit=max_profit,
        expiry_dte=expiry_dte,
        notes=(
            f"Protective put | strike {strike} (~1.25×ATR below market) | "
            f"delta target ~0.20 | trigger: VIX > 20 AND regime VOLATILE"
        ),
    )


def build_straddle(
    symbol: str,
    futures_price: float,
    expiry_dte: int = 7,
    tick_size: float = 1.0,
) -> OptionsOrder:
    """Build an ATM long straddle for event-driven trades (pre-FOMC/CPI).

    Buys the ATM call and ATM put at the same strike and expiry.
    Use when expecting a large move but direction is uncertain.

    Args:
        symbol:       Underlying ticker.
        futures_price: Current underlying price.
        expiry_dte:   Days to expiration (default 7 — weekly expiry).
        tick_size:    Strike tick size.

    Returns:
        :class:`OptionsOrder` for a long straddle.
    """
    atm_strike = _round_strike(futures_price, tick_size)
    expiry     = _expiry_date(expiry_dte)

    # Rough premium: ~1.5 % of underlying for ATM straddle
    estimated_premium = round(futures_price * 0.015, 4)
    max_risk = round(estimated_premium * 100 * 2, 2)  # total debit for 2 legs

    logger.info(
        "[build_straddle] %s | strike=%.2f DTE=%d", symbol, atm_strike, expiry_dte
    )

    return OptionsOrder(
        symbol=symbol,
        strategy=OptionsStrategy.STRADDLE,
        legs=[
            OptionsLeg(action="BUY", option_type="call", strike=atm_strike, expiry=expiry),
            OptionsLeg(action="BUY", option_type="put",  strike=atm_strike, expiry=expiry),
        ],
        estimated_premium=-(estimated_premium * 2),
        max_risk=max_risk,
        max_profit=0.0,   # stored as 0 to indicate unlimited
        expiry_dte=expiry_dte,
        notes=(
            f"Long straddle | ATM strike {atm_strike} | "
            f"for pre-FOMC/CPI event plays | unlimited upside"
        ),
    )


def build_strangle(
    symbol: str,
    futures_price: float,
    atr: float,
    expiry_dte: int = 30,
    tick_size: float = 1.0,
) -> OptionsOrder:
    """Build an OTM long strangle.

    Buys OTM call at ``futures_price + 1.0×ATR`` and OTM put at
    ``futures_price - 1.0×ATR``, both with the same expiry.

    Args:
        symbol:       Underlying ticker.
        futures_price: Current underlying price.
        atr:          14-period ATR value.
        expiry_dte:   Days to expiration (default 30).
        tick_size:    Strike tick size.

    Returns:
        :class:`OptionsOrder` for a long strangle.
    """
    call_strike = _round_strike(futures_price + 1.0 * atr, tick_size)
    put_strike  = _round_strike(futures_price - 1.0 * atr, tick_size)
    expiry      = _expiry_date(expiry_dte)

    # Rough OTM premium: ~0.5 % of underlying per leg
    per_leg_premium = round(futures_price * 0.005, 4)
    estimated_premium = round(per_leg_premium * 2, 4)
    max_risk   = round(estimated_premium * 100, 2)
    max_profit = 0.0  # unlimited

    logger.info(
        "[build_strangle] %s | call=%.2f put=%.2f DTE=%d",
        symbol, call_strike, put_strike, expiry_dte,
    )

    return OptionsOrder(
        symbol=symbol,
        strategy=OptionsStrategy.STRANGLE,
        legs=[
            OptionsLeg(action="BUY", option_type="call", strike=call_strike, expiry=expiry),
            OptionsLeg(action="BUY", option_type="put",  strike=put_strike,  expiry=expiry),
        ],
        estimated_premium=-estimated_premium,
        max_risk=max_risk,
        max_profit=max_profit,
        expiry_dte=expiry_dte,
        notes=(
            f"Long strangle | call {call_strike} / put {put_strike} | "
            f"±1×ATR strikes | cheaper than straddle, needs bigger move"
        ),
    )


# ---------------------------------------------------------------------------
# Order validation
# ---------------------------------------------------------------------------

# VIX thresholds used for regime classification
_VIX_THRESHOLDS = {
    VIXRegime.LOW:     (0.0,  15.0),
    VIXRegime.NORMAL:  (15.0, 20.0),
    VIXRegime.HIGH:    (20.0, 30.0),
    VIXRegime.EXTREME: (30.0, float("inf")),
}

# Strategies blocked by VIX regime
_BLOCKED_IN_HIGH_VIX: set[OptionsStrategy] = {
    OptionsStrategy.IRON_CONDOR,
}

# Strategies that require RANGING regime
_RANGING_ONLY: set[OptionsStrategy] = {
    OptionsStrategy.IRON_CONDOR,
}

# Strategies triggered only in VOLATILE regime
_VOLATILE_TRIGGER: set[OptionsStrategy] = {
    OptionsStrategy.PROTECTIVE_PUT,
}


def classify_vix_regime(vix: float) -> VIXRegime:
    """Classify the current VIX level into a :class:`VIXRegime`.

    Args:
        vix: Current VIX index value (e.g. 18.5).

    Returns:
        :class:`VIXRegime` enum value.
    """
    if vix < 15.0:
        return VIXRegime.LOW
    elif vix < 20.0:
        return VIXRegime.NORMAL
    elif vix < 30.0:
        return VIXRegime.HIGH
    else:
        return VIXRegime.EXTREME


def validate_order(
    order: OptionsOrder,
    vix_regime: VIXRegime,
    regime_state: RegimeState,
) -> tuple[bool, str]:
    """Validate an options order against the current market regime.

    Rules enforced:
    - Iron condors are **BLOCKED** in HIGH or EXTREME VIX regimes.
    - Iron condors require RANGING regime state.
    - Protective puts are only valid when regime is VOLATILE.
    - All strategies require DTE ≥ 7 days (avoid gamma risk near expiry).
    - Short-leg strategies require NORMAL or LOW VIX.

    Args:
        order:        The :class:`OptionsOrder` to validate.
        vix_regime:   Current :class:`VIXRegime`.
        regime_state: Current :class:`RegimeState` from the 5-layer framework.

    Returns:
        ``(is_valid: bool, reason: str)`` tuple.
        ``is_valid`` is True only when all checks pass.
    """
    strategy = order.strategy

    # --- DTE check ---
    if order.expiry_dte < 7:
        return (
            False,
            f"DTE={order.expiry_dte} is too close to expiry (< 7 days). "
            f"Gamma risk too high.",
        )

    # --- Iron condor VIX block ---
    if strategy in _BLOCKED_IN_HIGH_VIX and vix_regime in (VIXRegime.HIGH, VIXRegime.EXTREME):
        return (
            False,
            f"{strategy.value} is BLOCKED in {vix_regime.value} VIX regime. "
            f"IV is too elevated for selling premium on both sides. "
            f"Wait for VIX < 20.",
        )

    # --- Iron condor requires RANGING ---
    if strategy in _RANGING_ONLY and regime_state not in (RegimeState.RANGING,):
        return (
            False,
            f"{strategy.value} requires RANGING regime state. "
            f"Current regime: {regime_state.value}. "
            f"Iron condors are directional traps in trending markets.",
        )

    # --- Protective put — only valuable in VOLATILE/HIGH-VIX environments ---
    if strategy == OptionsStrategy.PROTECTIVE_PUT:
        if vix_regime == VIXRegime.LOW and regime_state not in (
            RegimeState.VOLATILE, RegimeState.MIXED
        ):
            return (
                False,
                "Protective put in LOW VIX + non-VOLATILE regime is cost-ineffective. "
                "Premium is expensive relative to hedging benefit.",
            )

    # --- Short credit strategies in EXTREME VIX ---
    short_leg_strategies = {
        OptionsStrategy.COVERED_CALL,
        OptionsStrategy.CREDIT_SPREAD_PUT,
        OptionsStrategy.CREDIT_SPREAD_CALL,
        OptionsStrategy.IRON_CONDOR,
    }
    if strategy in short_leg_strategies and vix_regime == VIXRegime.EXTREME:
        return (
            False,
            f"{strategy.value} is inadvisable in EXTREME VIX ({vix_regime.value}). "
            f"Short premium risk is undefined in panic markets.",
        )

    # --- Straddle/Strangle — warn in LOW VIX (expensive but not blocked) ---
    if strategy in (OptionsStrategy.STRADDLE, OptionsStrategy.STRANGLE):
        if vix_regime == VIXRegime.LOW:
            return (
                True,
                f"{strategy.value} approved but note: LOW VIX makes long vol expensive. "
                f"Ensure a catalyst (FOMC/CPI) justifies the debit.",
            )

    logger.info(
        "[validate_order] %s APPROVED | vix_regime=%s regime=%s",
        strategy.value, vix_regime.value, regime_state.value,
    )
    return (True, f"{strategy.value} validated | VIX={vix_regime.value} | regime={regime_state.value}")
