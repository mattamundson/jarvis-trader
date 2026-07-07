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
    # Micro futures — primary JARVIS universe
    "MES": 5.0,      # Micro E-mini S&P 500
    "MNQ": 2.0,      # Micro E-mini Nasdaq-100
    "MCL": 100.0,    # Micro WTI Crude Oil
    "MGC": 10.0,     # Micro Gold
    "MHG": 2500.0,   # Micro Copper (used by safety-layer gating)
    "M2K": 5.0,      # Micro Russell 2000
    "MSI": 1000.0,   # Micro Silver
    # Full-size S&P / Nasdaq futures — used by morning_brief for display context
    "ES": 50.0,
    "NQ": 20.0,
    # Continuous / front-month tickers (Yahoo / ib_insync style)
    "MES=F": 5.0,
    "NQ=F": 2.0,
    "CL=F": 100.0,
    "GC=F": 10.0,
}

# Default multiplier when symbol is unknown — conservative $5 (same as MES)
_DEFAULT_MULTIPLIER = 5.0

# Spot crypto symbols sized by price, not per-point multiplier. See
# `calculate_crypto_position_size` below. This set is consulted by the order
# router as well to choose between futures-style and crypto-style sizing.
CRYPTO_SPOT_SYMBOLS: set[str] = {
    "BTCUSD",
    "ETHUSD",
    "SOLUSD",
    "XBTUSD",  # Kraken's alias for BTCUSD
}


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


def apply_vol_target_scaling(
    contracts: int,
    symbol: str,
    realized_vol_ann_pct: float | None,
    target_vol_by_symbol: dict[str, float] | None,
    max_leverage: float = 3.0,
    max_contracts: int = 2,
) -> tuple[int, str]:
    """
    Volatility-targeting position-size overlay (pure function, gate it upstream).

    Scales an already-computed contract count toward a constant target
    volatility, so quiet regimes size up and turbulent regimes size down:

        w      = clip(target_vol / realized_vol, 0, max_leverage)
        scaled = clamp(round(contracts * w), 1, max_contracts)

    This is the live-sizer analogue of the backtest overlay validated in
    ``backtest/vol_target_wfo.py`` (MGC trend: OOS Sharpe +0.69, MaxDD -59%).
    It is a *risk overlay only* — it never creates or vetoes a trade, only
    rescales size, and it floors at 1 contract to match the rest of the sizer
    (an approved trade is never zeroed out). Integer contract granularity means
    the effect is coarser for micros than the continuous backtest weight.

    Caller is responsible for the enable gate (``settings.VOL_TARGET_ENABLED``);
    this function is a no-op passthrough whenever it lacks the inputs to scale.

    Args:
        contracts: Base contract count from the upstream sizing chain.
        symbol: Instrument ticker (looked up in ``target_vol_by_symbol``).
        realized_vol_ann_pct: 20-bar annualized realized vol (%) at decision
            time (the live ``rv_20_ann_pct`` technical indicator). None/<=0 =>
            passthrough.
        target_vol_by_symbol: Per-symbol target annualized vol (%). A symbol
            missing from the map => passthrough (overlay does not apply).
        max_leverage: Clip ceiling on the up-scaling multiplier.
        max_contracts: Hard ceiling; the scaled result is clamped to it.

    Returns:
        (scaled_contracts, reasoning) — ``scaled_contracts == contracts`` on any
        passthrough path.
    """
    if contracts <= 0:
        return contracts, "no base contracts; vol-target passthrough"

    target = (target_vol_by_symbol or {}).get(symbol)
    if target is None or target <= 0:
        return contracts, f"no target_vol configured for {symbol}; vol-target passthrough"

    if realized_vol_ann_pct is None or realized_vol_ann_pct <= 0:
        return contracts, "realized vol unavailable; vol-target passthrough"

    w = min(max(target / realized_vol_ann_pct, 0.0), max_leverage)
    scaled = max(1, min(int(round(contracts * w)), max_contracts))
    reasoning = (
        f"vol-target: target={target:.2f}% / rv={realized_vol_ann_pct:.2f}% "
        f"=> w={w:.2f} (cap {max_leverage:.1f}); contracts {contracts} -> {scaled} "
        f"[clamp 1..{max_contracts}]"
    )
    return scaled, reasoning


# ---------------------------------------------------------------------------
# Spot crypto sizing — fractional quantity instead of per-point multipliers
# ---------------------------------------------------------------------------
@dataclass
class CryptoPositionSizeResult:
    """Parallel to PositionSizeResult for crypto — quantity is fractional."""

    quantity: float           # fractional units (e.g. 0.012 BTC)
    risk_per_trade: float
    stop_distance: float      # absolute $ distance used as stop
    dollar_risk_per_unit: float
    account_value: float
    symbol: str
    reasoning: str


def calculate_crypto_position_size(
    symbol: str,
    account_value: float,
    spot_price: float,
    atr_pct: float,
    risk_pct: float = 0.01,
    atr_stop_multiplier: float = 0.70,
    max_notional_pct: float = 0.25,
    min_quantity: float = 0.0,
) -> CryptoPositionSizeResult:
    """
    Price-based fractional sizing for spot crypto (no per-point multiplier).

        risk_budget       = account_value * risk_pct
        stop_distance     = spot_price * atr_pct * atr_stop_multiplier
        qty               = risk_budget / stop_distance

    Then cap notional at `max_notional_pct` of account to prevent a single
    crypto position from dominating the book. Divergence from futures sizing:

      - Futures use INSTRUMENT_MULTIPLIERS ($/pt) and integer contracts
        clamped to MAX_CONTRACTS_PER_INSTRUMENT.
      - Crypto uses spot price as its own multiplier and returns a float
        quantity (e.g. 0.012 BTC). A quantity floor of `min_quantity` (0.0
        by default) can be raised by callers to enforce exchange minimums
        — Kraken's BTC minimum is 0.0001, ETH 0.01.

    Edge cases: non-positive price/atr → qty=0.0 (caller should abstain).
    """
    if spot_price is None or spot_price <= 0:
        return CryptoPositionSizeResult(
            quantity=0.0,
            risk_per_trade=0.0,
            stop_distance=0.0,
            dollar_risk_per_unit=0.0,
            account_value=account_value,
            symbol=symbol,
            reasoning="spot_price missing or non-positive — abstaining",
        )
    if atr_pct is None or atr_pct <= 0:
        return CryptoPositionSizeResult(
            quantity=0.0,
            risk_per_trade=0.0,
            stop_distance=0.0,
            dollar_risk_per_unit=0.0,
            account_value=account_value,
            symbol=symbol,
            reasoning="atr_pct missing or non-positive — abstaining",
        )

    risk_per_trade = account_value * risk_pct
    stop_distance = spot_price * atr_pct * atr_stop_multiplier
    dollar_risk_per_unit = stop_distance  # 1 unit = 1 coin = 1 * stop_distance $

    if dollar_risk_per_unit <= 0:
        qty = 0.0
    else:
        qty = risk_per_trade / dollar_risk_per_unit

    # Notional cap: qty * spot_price must not exceed max_notional_pct of account
    notional_cap = account_value * max_notional_pct
    if qty * spot_price > notional_cap:
        qty = notional_cap / spot_price

    if qty < min_quantity:
        qty = 0.0  # below exchange minimum — abstain rather than round up

    reasoning = (
        f"Symbol={symbol} | Account=${account_value:,.2f} | "
        f"Risk={risk_pct:.1%} => ${risk_per_trade:,.2f} | "
        f"Spot=${spot_price:,.2f} ATR%={atr_pct:.2%} x {atr_stop_multiplier:.0%} "
        f"=> stop=${stop_distance:,.2f} | Qty=${risk_per_trade:,.2f}/${stop_distance:,.2f}"
        f"={qty:.6f} | Notional cap={max_notional_pct:.0%} => ${notional_cap:,.2f}"
    )
    logger.info(f"[CryptoSizing] {reasoning}")

    return CryptoPositionSizeResult(
        quantity=round(qty, 8),
        risk_per_trade=risk_per_trade,
        stop_distance=stop_distance,
        dollar_risk_per_unit=dollar_risk_per_unit,
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
