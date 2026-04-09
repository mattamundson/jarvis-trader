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


# ---------------------------------------------------------------------------
# Half-Kelly position sizing
# ---------------------------------------------------------------------------


def calculate_half_kelly_size(
    capital: float,
    win_rate: float,
    avg_win_loss_ratio: float,
    tick_value: float,
    atr_ticks: float,
    stop_atr_mult: float = 0.70,
    max_risk_pct: float = 0.06,
    min_contracts: int = 1,
    max_contracts: int = 2,
) -> dict:
    """
    Half-Kelly position sizing with multiple safety caps.

    Kelly fraction = (win_rate * avg_win_loss_ratio - loss_rate) / avg_win_loss_ratio
    Half-Kelly = Kelly / 2 (fractional Kelly for robustness against estimation error)

    Falls back to min_contracts when edge is zero or negative.
    Hard cap at max_risk_pct (6%) to prevent overbetting on noisy estimates.

    Returns dict: contracts, risk_pct, method, kelly_fraction, dollar_risk
    """
    loss_rate = 1.0 - win_rate

    if avg_win_loss_ratio <= 0:
        return {
            'contracts': min_contracts, 'risk_pct': 0.01,
            'method': 'fixed_fallback', 'kelly_fraction': 0.0,
            'dollar_risk': capital * 0.01
        }

    kelly_fraction = (win_rate * avg_win_loss_ratio - loss_rate) / avg_win_loss_ratio
    half_kelly = kelly_fraction / 2.0

    if half_kelly <= 0:
        return {
            'contracts': min_contracts, 'risk_pct': 0.01,
            'method': 'no_edge_minimum', 'kelly_fraction': kelly_fraction,
            'dollar_risk': capital * 0.01
        }

    risk_pct = min(half_kelly, max_risk_pct)

    stop_dollars = atr_ticks * stop_atr_mult * tick_value
    if stop_dollars <= 0:
        return {
            'contracts': min_contracts, 'risk_pct': risk_pct,
            'method': 'stop_zero_fallback', 'kelly_fraction': kelly_fraction,
            'dollar_risk': capital * risk_pct
        }

    dollar_risk = capital * risk_pct
    raw_contracts = dollar_risk / stop_dollars
    contracts = max(min_contracts, min(max_contracts, round(raw_contracts)))

    return {
        'contracts': contracts,
        'risk_pct': risk_pct,
        'method': 'half_kelly',
        'kelly_fraction': kelly_fraction,
        'half_kelly': half_kelly,
        'dollar_risk': dollar_risk,
        'stop_dollars': stop_dollars,
    }


def compute_rolling_edge(
    recent_trades: list,
    window: int = 20,
) -> dict:
    """
    Compute edge metrics from last N closed paper trades.

    Each trade in recent_trades should be a dict with a 'pnl' key (float).
    Returns 'sufficient_data': False if fewer than 10 trades.

    Returns: {sufficient_data, n_trades, win_rate, avg_win_loss_ratio, edge_pct}
    """
    if len(recent_trades) < 10:
        return {'sufficient_data': False, 'n_trades': len(recent_trades)}

    trades = recent_trades[-window:]
    wins = [t['pnl'] for t in trades if t.get('pnl', 0) > 0]
    losses = [abs(t['pnl']) for t in trades if t.get('pnl', 0) <= 0]

    win_rate = len(wins) / len(trades) if trades else 0
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 1

    return {
        'sufficient_data': True,
        'n_trades': len(trades),
        'win_rate': win_rate,
        'avg_win_loss_ratio': avg_win / avg_loss if avg_loss > 0 else 0,
        'edge_pct': win_rate - (1 - win_rate) * (avg_loss / avg_win) if avg_win > 0 else 0,
    }
