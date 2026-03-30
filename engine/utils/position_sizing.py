"""
JARVIS TRADER — Fixed-Fractional Position Sizing
Implements the 1%-risk per trade formula from strategy-reference.md

Formula:
    risk_per_trade          = account_value * risk_pct          (default 1%)
    stop_distance           = atr * atr_stop_multiplier         (default 70% of ATR)
    dollar_risk_per_contract = stop_distance * contract_multiplier
    raw_contracts           = floor(risk_per_trade / dollar_risk_per_contract)
    contracts               = clamp(raw_contracts, 1, max_contracts)

Contract multipliers ($ per point):
    MES  / MES=F  — Micro E-mini S&P 500  — $5.00/pt
    MNQ  / NQ=F   — Micro E-mini Nasdaq   — $2.00/pt
    MCL  / CL=F   — Micro Crude Oil        — $100.00/pt
"""

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Instrument multiplier table  ($ per 1 full point of price movement)
# ---------------------------------------------------------------------------
INSTRUMENT_MULTIPLIERS: dict[str, float] = {
    # Root symbols used inside JARVIS
    "MES": 5.0,
    "MNQ": 2.0,
    "MCL": 100.0,
    # Continuous / front-month futures tickers (Yahoo / ib_insync style)
    "MES=F": 5.0,
    "NQ=F": 2.0,
    "CL=F": 100.0,
}

# Default multiplier when symbol is unknown — conservative $5 (same as MES)
_DEFAULT_MULTIPLIER = 5.0


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------
@dataclass
class PositionSizeResult:
    """
    All inputs and outputs of a position-size calculation, preserved for
    audit logging and dashboard display.
    """

    contracts: int  # Final clamped contract count (>= 1)
    risk_per_trade: float  # Dollar risk budget for this trade
    stop_distance: float  # Price-point distance used as stop (atr * multiplier)
    dollar_risk_per_contract: float  # Dollar risk per contract at stop
    account_value: float  # Account value used in the calculation
    symbol: str  # Instrument symbol
    reasoning: str  # Human-readable walk-through of the math


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_contract_multiplier(symbol: str) -> float:
    """
    Return the dollar-per-point multiplier for *symbol*.

    Looks up INSTRUMENT_MULTIPLIERS (case-insensitive on the root part).
    Falls back to _DEFAULT_MULTIPLIER and logs a warning if unknown.
    """
    # Try exact match first
    multiplier = INSTRUMENT_MULTIPLIERS.get(symbol)
    if multiplier is not None:
        return multiplier

    # Try upper-case
    multiplier = INSTRUMENT_MULTIPLIERS.get(symbol.upper())
    if multiplier is not None:
        return multiplier

    logger.warning(
        f"[PositionSizing] Unknown symbol '{symbol}' — defaulting multiplier to "
        f"${_DEFAULT_MULTIPLIER}/pt. Add it to INSTRUMENT_MULTIPLIERS if needed."
    )
    return _DEFAULT_MULTIPLIER


def validate_size(contracts: int, max_contracts: int) -> int:
    """
    Clamp *contracts* to the range [1, max_contracts].

    Always returns at least 1 (we never size to 0 for a live trade signal)
    and never returns more than the configured paper-phase ceiling.
    """
    return max(1, min(contracts, max_contracts))


def calculate_position_size(
    symbol: str,
    account_value: float,
    atr: float | None,
    risk_pct: float = 0.01,
    atr_stop_multiplier: float = 0.70,
    max_contracts: int = 2,
) -> PositionSizeResult:
    """
    Fixed-fractional position sizing using a stop defined as a fraction of ATR.

    Args:
        symbol:              Instrument ticker (e.g. "MES", "MNQ", "MCL").
        account_value:       Current account equity in USD.
        atr:                 Average True Range in price points (14-period, same
                             timeframe as the trading signal). Pass None or 0.0
                             to trigger the safe fallback of 1 contract.
        risk_pct:            Fraction of account to risk per trade (default 0.01 = 1%).
        atr_stop_multiplier: Stop distance as a multiple of ATR (default 0.70 = 70%).
        max_contracts:       Hard ceiling from config (default 2 for paper phase).

    Returns:
        PositionSizeResult with the final contract count and full calculation
        details for audit logging.

    Edge-case handling:
        - atr is None or <= 0  → fallback to 1 contract (cannot size without ATR)
        - account_value < 1000 → fallback to 1 contract (account too small to size)
        - unknown symbol       → uses _DEFAULT_MULTIPLIER ($5/pt) with warning
        - raw_contracts == 0   → clamped up to 1 (always trade at least 1 lot)
    """
    multiplier = get_contract_multiplier(symbol)

    # ── Edge case: insufficient account value ──────────────────────────────
    if account_value < 1000.0:
        reasoning = (
            f"Account value ${account_value:,.2f} is below the $1,000 minimum required "
            f"for position sizing. Defaulting to 1 contract."
        )
        logger.warning(f"[PositionSizing] {reasoning}")
        return PositionSizeResult(
            contracts=1,
            risk_per_trade=0.0,
            stop_distance=0.0,
            dollar_risk_per_contract=0.0,
            account_value=account_value,
            symbol=symbol,
            reasoning=reasoning,
        )

    # ── Edge case: ATR unavailable or zero ────────────────────────────────
    if not atr or atr <= 0.0:
        reasoning = (
            f"ATR is {'None' if atr is None else atr} — cannot compute stop distance. "
            f"Defaulting to 1 contract (conservative fallback)."
        )
        logger.warning(f"[PositionSizing] {symbol}: {reasoning}")
        return PositionSizeResult(
            contracts=1,
            risk_per_trade=account_value * risk_pct,
            stop_distance=0.0,
            dollar_risk_per_contract=0.0,
            account_value=account_value,
            symbol=symbol,
            reasoning=reasoning,
        )

    # ── Core formula ───────────────────────────────────────────────────────
    risk_per_trade = account_value * risk_pct  # e.g. $10,000 * 0.01 = $100
    stop_distance = atr * atr_stop_multiplier  # e.g. 10.0 pts * 0.70 = 7.0 pts
    dollar_risk_per_contract = stop_distance * multiplier  # e.g. 7.0 * $5 = $35

    if dollar_risk_per_contract <= 0.0:
        # Safeguard against floating-point edge cases
        raw_contracts = 1
    else:
        raw_contracts = math.floor(risk_per_trade / dollar_risk_per_contract)

    contracts = validate_size(raw_contracts, max_contracts)

    reasoning = (
        f"Symbol={symbol} | Account=${account_value:,.2f} | "
        f"Risk budget={risk_pct:.1%} => ${risk_per_trade:,.2f} | "
        f"ATR={atr:.4f} pts x {atr_stop_multiplier:.0%} = stop={stop_distance:.4f} pts | "
        f"$/contract={stop_distance:.4f} x ${multiplier}/pt = ${dollar_risk_per_contract:,.2f} | "
        f"Raw contracts=floor({risk_per_trade:,.2f}/{dollar_risk_per_contract:,.2f})={raw_contracts} | "
        f"After clamp [1, {max_contracts}] => {contracts} contract(s)"
    )

    logger.info(f"[PositionSizing] {reasoning}")

    return PositionSizeResult(
        contracts=contracts,
        risk_per_trade=risk_per_trade,
        stop_distance=stop_distance,
        dollar_risk_per_contract=dollar_risk_per_contract,
        account_value=account_value,
        symbol=symbol,
        reasoning=reasoning,
    )
