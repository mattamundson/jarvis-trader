"""
JARVIS Trader Options Engine — Premium Calculator
Black-76 pricing (options on futures), probability of profit, expected value,
spread metrics.

Black-76 (not spot Black-Scholes) is the correct model here: every symbol this
engine trades (MES/MNQ/MCL/MGC) is a future, and a futures price is already a
martingale under the T-forward measure — no risk-free drift term belongs in d1.
"""

import logging
import math
from dataclasses import dataclass
from datetime import date
from typing import Literal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: normal distribution
# ---------------------------------------------------------------------------


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1_d2(F: float, K: float, T: float, sigma: float) -> tuple[float, float]:
    """Compute d1 and d2 for Black-76 (no risk-free drift term — F is already
    a martingale under the T-forward measure)."""
    if T <= 0:
        raise ValueError("T must be > 0")
    if sigma <= 0:
        raise ValueError("sigma must be > 0")
    log_fk = math.log(F / K)
    d1 = (log_fk + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


# ---------------------------------------------------------------------------
# Black-76 price
# ---------------------------------------------------------------------------


def black76_price(
    F: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: Literal["call", "put"],
) -> float:
    """Calculate the Black-76 theoretical option-on-futures price.

    Args:
        F:           Futures price (underlying).
        K:           Strike price.
        T:           Time to expiry in years.
        r:           Annualised risk-free rate (decimal) — used only to discount
                     the expected payoff back to present value.
        sigma:       Annualised implied volatility (decimal).
        option_type: ``"call"`` or ``"put"``.

    Returns:
        Theoretical option price (always ≥ 0).
    """
    otype = option_type.lower()

    # Handle expiry edge case
    if T <= 0:
        intrinsic = max(F - K, 0.0) if otype == "call" else max(K - F, 0.0)
        return round(intrinsic, 4)

    d1, d2 = _d1_d2(F, K, T, sigma)
    disc = math.exp(-r * T)

    if otype == "call":
        price = disc * (F * _norm_cdf(d1) - K * _norm_cdf(d2))
    elif otype == "put":
        price = disc * (K * _norm_cdf(-d2) - F * _norm_cdf(-d1))
    else:
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")

    return round(max(price, 0.0), 4)


# ---------------------------------------------------------------------------
# Probability of profit
# ---------------------------------------------------------------------------


def probability_of_profit(
    F: float,
    K: float,
    T: float,
    sigma: float,
    option_type: Literal["call", "put"],
    target_pct: float = 0.5,
) -> float:
    """Estimate the probability that an option expires in profit for the buyer.

    Uses the risk-neutral probability that the option expires in-the-money.
    Under Black-76 the drift term drops out of d1/d2 entirely (F is already a
    martingale under the T-forward measure), so this probability has no
    dependence on the risk-free rate — ``r`` is intentionally not a parameter.

    For *short* options strategies (credit), the seller's PoP = 1 - buyer's PoP.

    Args:
        F:          Futures price (underlying).
        K:          Strike price.
        T:          Time to expiry in years.
        sigma:      Annualised implied volatility (decimal).
        option_type: ``"call"`` or ``"put"``.
        target_pct: Fraction of premium to treat as the profit target for
                    probability calculation (default 0.50 = 50 % of premium).
                    Unused in the current implementation; the function returns
                    the probability of expiring ITM for the buyer.

    Returns:
        Probability in [0, 1] that the option expires ITM for the long holder.
    """
    if T <= 0:
        if option_type.lower() == "call":
            return 1.0 if F > K else 0.0
        return 1.0 if F < K else 0.0

    _, d2 = _d1_d2(F, K, T, sigma)

    if option_type.lower() == "call":
        prob_itm = _norm_cdf(d2)
    else:
        prob_itm = _norm_cdf(-d2)

    return round(prob_itm, 6)


# ---------------------------------------------------------------------------
# Expected value
# ---------------------------------------------------------------------------


def expected_value(
    premium: float,
    prob_profit: float,
    max_profit: float,
    max_loss: float,
) -> float:
    """Calculate the expected value of an options trade.

    EV = prob_profit × max_profit − (1 − prob_profit) × max_loss

    Args:
        premium:     Net premium collected (positive = credit).
        prob_profit: Probability of the trade being profitable [0, 1].
        max_profit:  Maximum dollar profit (positive number).
        max_loss:    Maximum dollar loss (positive number, represents magnitude).

    Returns:
        Expected value in dollars.  Positive EV suggests edge.
    """
    prob_loss = 1.0 - prob_profit
    ev = prob_profit * max_profit - prob_loss * max_loss
    return round(ev, 4)


# ---------------------------------------------------------------------------
# Dataclass for scan results
# ---------------------------------------------------------------------------


@dataclass
class PremiumScanResult:
    """Result of a premium scan across a specific options strategy."""

    symbol: str
    strategy_type: str
    strikes: list[float]
    expiry: date
    greeks: dict[str, float]
    pnl_scenarios: dict[str, float]  # e.g. {"at_expiry_ITM": -300, "at_expiry_OTM": 120}
    theoretical_price: float = 0.0
    probability_of_profit: float = 0.0
    expected_value: float = 0.0
    notes: str = ""

    def summary(self) -> str:
        return (
            f"[{self.symbol}] {self.strategy_type} | strikes={self.strikes} "
            f"expiry={self.expiry} | PoP={self.probability_of_profit:.1%} "
            f"EV=${self.expected_value:.2f} | Δ={self.greeks.get('delta', 0):.4f}"
        )


# ---------------------------------------------------------------------------
# Credit spread metrics
# ---------------------------------------------------------------------------


def get_credit_spread_metrics(
    sell_strike: float,
    buy_strike: float,
    sell_premium: float,
    buy_premium: float,
) -> dict[str, float]:
    """Calculate key metrics for a vertical credit spread.

    Works for both bull put spreads and bear call spreads:
    - Bull put spread: sell higher put, buy lower put (sell_strike > buy_strike)
    - Bear call spread: sell lower call, buy higher call (sell_strike < buy_strike)

    Args:
        sell_strike:  Strike price of the option sold (short leg).
        buy_strike:   Strike price of the option bought (long leg/hedge).
        sell_premium: Premium received for the short leg.
        buy_premium:  Premium paid for the long leg.

    Returns:
        Dictionary with the following keys:
        - net_premium:       Net credit received per share.
        - max_profit:        Maximum profit (= net_premium per share × 100).
        - max_risk:          Maximum loss per spread.
        - breakeven:         Underlying price at breakeven.
        - risk_reward_ratio: max_risk / max_profit (lower is better for credit).
        - pop:               Approximate probability of profit based on width vs credit.
    """
    net_premium = round(sell_premium - buy_premium, 4)
    spread_width = abs(sell_strike - buy_strike)

    max_profit = round(net_premium * 100, 2)  # one options contract = 100 shares
    max_risk = round((spread_width - net_premium) * 100, 2)

    # Breakeven: depends on spread direction
    # Bull put (sell higher): breakeven = sell_strike - net_premium
    # Bear call (sell lower): breakeven = sell_strike + net_premium
    if sell_strike > buy_strike:
        # Bull put spread
        breakeven = round(sell_strike - net_premium, 4)
    else:
        # Bear call spread
        breakeven = round(sell_strike + net_premium, 4)

    risk_reward_ratio = round(max_risk / max_profit, 4) if max_profit > 0 else float("inf")

    # Rough PoP: credit / spread_width as a fraction (not model-based)
    pop = round(net_premium / spread_width, 4) if spread_width > 0 else 0.0
    pop = max(0.0, min(1.0, pop))

    return {
        "net_premium": net_premium,
        "max_profit": max_profit,
        "max_risk": max_risk,
        "breakeven": breakeven,
        "risk_reward_ratio": risk_reward_ratio,
        "pop": pop,
    }


# ---------------------------------------------------------------------------
# PnL scenarios at expiry
# ---------------------------------------------------------------------------


def pnl_at_expiry(
    underlying_price: float,
    sell_strike: float,
    buy_strike: float,
    net_premium: float,
    option_type: Literal["call", "put"],
    contracts: int = 1,
) -> float:
    """Calculate the P&L at expiry for a vertical spread position.

    Args:
        underlying_price: Hypothetical underlying price at expiry.
        sell_strike:      Short leg strike price.
        buy_strike:       Long leg strike price.
        net_premium:      Net credit received per share.
        option_type:      ``"call"`` or ``"put"`` (type of both legs).
        contracts:        Number of contracts (default 1).

    Returns:
        P&L in dollars (positive = profit, negative = loss).
    """
    mult = 100 * contracts
    otype = option_type.lower()

    if otype == "put":
        # Bull put spread: short higher strike, long lower strike
        short_pnl = max(sell_strike - underlying_price, 0.0)
        long_pnl = max(buy_strike - underlying_price, 0.0)
        spread_pnl = net_premium - (short_pnl - long_pnl)
    elif otype == "call":
        # Bear call spread: short lower strike, long higher strike
        short_pnl = max(underlying_price - sell_strike, 0.0)
        long_pnl = max(underlying_price - buy_strike, 0.0)
        spread_pnl = net_premium - (short_pnl - long_pnl)
    else:
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")

    return round(spread_pnl * mult, 2)
