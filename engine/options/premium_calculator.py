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
from typing import Literal, Optional

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
# Expected move (ATM straddle)
# ---------------------------------------------------------------------------


def expected_move(
    F: float,
    T: float,
    sigma: float,
    r: float = 0.0,
    K: Optional[float] = None,
) -> dict:
    """Compute the options-market "Expected Move" — the 1-standard-deviation
    price range implied by the ATM straddle.

    The market convention is that the price of an at-the-money straddle
    (ATM call + ATM put) approximates the range the underlying is expected
    to move (up or down) by expiration, at roughly 1-sigma confidence. This
    function returns BOTH:

    1. The **exact** value — the real Black-76 ATM straddle price
       (``black76_price(F, K, T, r, sigma, "call") + black76_price(F, K, T,
       r, sigma, "put")``). This is the primary number: it is model-consistent
       with every other premium this engine computes, and is preferred
       whenever an exact pricer is available (it is, here).
    2. The **0.8-approximation** — the textbook shorthand
       ``EM ≈ 0.8 * F * sigma * sqrt(T)`` — returned only as a sanity
       cross-check against the exact value.

    Derivation of the 0.8 factor (for the curious / for reviewers): at the
    ATM strike (K=F), d1 = -d2 = 0.5*sigma*sqrt(T), and the straddle price
    reduces to ``disc * 2F * (N(d1) - N(d2)) = disc * 2F * (2*N(d1) - 1)``
    (using N(-x) = 1 - N(x)). For short-dated ATM options d1 is small, so a
    first-order Taylor expansion of N(d1) around 0 — N(d1) ≈ 0.5 + phi(0)*d1,
    where phi(0) = 1/sqrt(2*pi) — gives
    ``straddle ≈ disc * F * sigma * sqrt(T) * sqrt(2/pi)``.
    ``sqrt(2/pi) ≈ 0.7979 ≈ 0.8``, and with `disc = exp(-r*T) ≈ 1` for
    short-dated / low-rate cases, this collapses to the familiar
    ``EM ≈ 0.8 * F * sigma * sqrt(T)`` heuristic. (Note: this is *not* the
    same claim as "N(d1) + N(-d1) ≈ 0.8" — N(d1) + N(-d1) is identically 1
    for any d1; the 0.8 factor instead comes from the small-d1 Taylor
    expansion above.) The approximation degrades as T or sigma grows large
    enough that d1 is no longer small, or when K != F.

    Args:
        F:     Futures price (underlying).
        T:     Time to expiry in years.
        sigma: Annualised implied volatility (decimal), typically ATM IV.
        r:     Annualised risk-free rate (decimal). Default 0.0 — the
               discount factor's effect on a short-dated ATM straddle is
               small and expected-move quotes are conventionally undiscounted;
               pass the real rate for a discounted (still-exact) figure.
        K:     Strike to price the straddle at. Defaults to the ATM strike
               (``K = F``) when not provided — use the nearest listed strike
               when an exact chain lookup is available.

    Returns:
        Dict with:
          - ``straddle_price``: exact Black-76 ATM call + put price (primary).
          - ``expected_move_dollars``: same as ``straddle_price`` (the
            1-sigma expected price range, in dollars).
          - ``expected_move_pct``: ``expected_move_dollars / F``.
          - ``approx_expected_move_dollars``: the ``0.8 * F * sigma *
            sqrt(T)`` textbook approximation (sanity cross-check only).
          - ``call_price`` / ``put_price``: the two straddle legs.
          - ``F`` / ``K`` / ``T`` / ``r`` / ``sigma``: inputs used, echoed
            back for easy API serialization / auditing.
    """
    if K is None:
        K = F

    call_price = black76_price(F, K, T, r, sigma, "call")
    put_price = black76_price(F, K, T, r, sigma, "put")
    straddle_price = round(call_price + put_price, 4)

    expected_move_dollars = straddle_price
    expected_move_pct = round(expected_move_dollars / F, 6) if F > 0 else 0.0
    approx_expected_move_dollars = round(0.8 * F * sigma * math.sqrt(T), 4)

    return {
        "F": F,
        "K": K,
        "T": T,
        "r": r,
        "sigma": sigma,
        "call_price": call_price,
        "put_price": put_price,
        "straddle_price": straddle_price,
        "expected_move_dollars": expected_move_dollars,
        "expected_move_pct": expected_move_pct,
        "approx_expected_move_dollars": approx_expected_move_dollars,
    }


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
