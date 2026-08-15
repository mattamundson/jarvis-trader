"""
JARVIS Trader Options Engine — Greeks Monitor
Black-76 Greeks calculator (options on futures), implied volatility solver,
IV rank/percentile, portfolio-level Greeks aggregation, and real-time delta
alert monitoring.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Black-Scholes core math
# ---------------------------------------------------------------------------


def _norm_cdf(x: float) -> float:
    """Cumulative distribution function of the standard normal distribution."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Probability density function of the standard normal distribution."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1_d2(
    F: float,
    K: float,
    T: float,
    sigma: float,
) -> tuple[float, float]:
    """Compute d1 and d2 for Black-76 (options on futures).

    No risk-free drift term — a futures price is already a martingale under
    the T-forward measure, unlike spot.

    Args:
        F: Futures price (underlying).
        K: Strike price.
        T: Time to expiration in years.
        sigma: Implied / historical volatility (annualised, decimal).

    Returns:
        (d1, d2) tuple.
    """
    if T <= 0:
        raise ValueError("Time to expiration T must be positive.")
    if sigma <= 0:
        raise ValueError("Volatility sigma must be positive.")
    log_fk = math.log(F / K)
    d1 = (log_fk + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


# ---------------------------------------------------------------------------
# Public API — Greeks
# ---------------------------------------------------------------------------


def calculate_greeks(
    F: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: Literal["call", "put"],
) -> dict[str, float]:
    """Calculate Black-76 Greeks for a single option on a future.

    Args:
        F:           Futures price (underlying).
        K:           Strike price.
        T:           Time to expiry in years (e.g. 30 days → 30/365).
        r:           Annualised risk-free rate (decimal, e.g. 0.05 for 5 %).
        sigma:       Annualised implied volatility (decimal, e.g. 0.20 for 20 %).
        option_type: ``"call"`` or ``"put"``.

    Returns:
        Dictionary with keys: delta, gamma, theta, vega, rho.
        - delta: Rate of change of option price with respect to the future.
        - gamma: Rate of change of delta.
        - theta: Time decay per calendar day (negative for long options).
        - vega:  Sensitivity to 1 % change in IV (value × 0.01).
        - rho:   Sensitivity to 1 % change in risk-free rate (value × 0.01).

    Notes on the Black-76 derivation (vs. spot Black-Scholes):
        Because both legs of the Black-76 price (``F*N(d1)`` and ``K*N(d2)``)
        are discounted by ``e^{-rT}`` — not just the strike leg, as in spot
        Black-Scholes where only ``K`` is discounted — delta, gamma, and vega
        all pick up an extra ``e^{-rT}`` factor relative to their spot-BS
        counterparts, and theta gains an additional ``± r*F*e^{-rT}*N(±d1)``
        term (see the derivation of ``d/dT[F*N(d1) - K*N(d2)]`` used below,
        which relies on the identity ``F*N'(d1) == K*N'(d2)``). Rho reduces to
        ``-T * price`` because, once the drift term drops out of d1/d2, the
        option price is exactly ``e^{-rT}`` times an r-independent expectation.
    """
    otype = option_type.lower()
    if otype not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")

    d1, d2 = _d1_d2(F, K, T, sigma)
    sqrt_T = math.sqrt(T)
    disc = math.exp(-r * T)

    # --- Delta ---
    if otype == "call":
        delta = disc * _norm_cdf(d1)
    else:
        delta = disc * (_norm_cdf(d1) - 1.0)  # negative for puts

    # --- Gamma (same for calls and puts) ---
    gamma = disc * _norm_pdf(d1) / (F * sigma * sqrt_T)

    # --- Theta (per calendar day) ---
    common_theta = -(F * _norm_pdf(d1) * sigma * disc) / (2.0 * sqrt_T)
    if otype == "call":
        theta = (common_theta - r * K * disc * _norm_cdf(d2) + r * F * disc * _norm_cdf(d1)) / 365.0
    else:
        theta = (common_theta + r * K * disc * _norm_cdf(-d2) - r * F * disc * _norm_cdf(-d1)) / 365.0

    # --- Vega (per 1 % move in IV) ---
    vega = F * disc * _norm_pdf(d1) * sqrt_T * 0.01

    # --- Rho (per 1 % move in risk-free rate) ---
    # price = e^{-rT} * (r-independent expectation) once the drift term drops
    # out of d1/d2, so d(price)/dr = -T * price for both calls and puts.
    from .premium_calculator import black76_price  # local import to avoid circulars

    price = black76_price(F, K, T, r, sigma, otype)
    rho = -T * price * 0.01

    return {
        "delta": round(delta, 6),
        "gamma": round(gamma, 6),
        "theta": round(theta, 6),
        "vega": round(vega, 6),
        "rho": round(rho, 6),
    }


# ---------------------------------------------------------------------------
# Implied volatility — Newton-Raphson solver
# ---------------------------------------------------------------------------


def implied_volatility(
    market_price: float,
    F: float,
    K: float,
    T: float,
    r: float,
    option_type: Literal["call", "put"],
    max_iter: int = 100,
    tol: float = 1e-6,
    sigma_init: float = 0.30,
) -> float:
    """Solve for implied volatility using the Newton-Raphson method.

    Args:
        market_price: Observed market price (mid-price recommended).
        F:            Futures price (underlying).
        K:            Strike price.
        T:            Time to expiry in years.
        r:            Annualised risk-free rate (decimal).
        option_type:  ``"call"`` or ``"put"``.
        max_iter:     Maximum iterations (default 100).
        tol:          Convergence tolerance (default 1e-6).
        sigma_init:   Initial volatility guess (default 0.30).

    Returns:
        Implied volatility as a decimal (e.g. 0.2345 for 23.45 %).
        Returns ``float('nan')`` if the solver fails to converge.
    """
    from .premium_calculator import black76_price  # local import to avoid circulars

    sigma = sigma_init
    for i in range(max_iter):
        price = black76_price(F, K, T, r, sigma, option_type)
        price_diff = price - market_price

        if abs(price_diff) < tol:
            return round(sigma, 6)

        # Vega is the derivative of price w.r.t. sigma (discounted, Black-76)
        try:
            d1, _ = _d1_d2(F, K, T, sigma)
        except ValueError:
            return float("nan")

        vega_raw = F * math.exp(-r * T) * _norm_pdf(d1) * math.sqrt(T)  # raw vega (not scaled)
        if abs(vega_raw) < 1e-10:
            logger.debug("IV solver: vega near zero at iter %d — stopping", i)
            return float("nan")

        sigma = sigma - price_diff / vega_raw

        # Clamp sigma to a sensible range to avoid divergence
        sigma = max(0.001, min(sigma, 20.0))

    logger.warning(
        "implied_volatility: Newton-Raphson did not converge for S=%s K=%s T=%s", S, K, T
    )
    return float("nan")


# ---------------------------------------------------------------------------
# IV rank and percentile
# ---------------------------------------------------------------------------


def iv_rank(
    current_iv: float,
    iv_52w_high: float,
    iv_52w_low: float,
) -> float:
    """Calculate IV Rank (IVR) relative to the 52-week range.

    IVR = (current_iv - low) / (high - low) × 100

    Args:
        current_iv:   Current implied volatility (decimal).
        iv_52w_high:  52-week high IV (decimal).
        iv_52w_low:   52-week low IV (decimal).

    Returns:
        IVR value in the range [0, 100].  Returns 0 if high == low.
    """
    iv_range = iv_52w_high - iv_52w_low
    if iv_range <= 0:
        return 0.0
    ivr = (current_iv - iv_52w_low) / iv_range * 100.0
    return round(max(0.0, min(100.0, ivr)), 2)


def iv_percentile(
    iv_history: list[float],
    current_iv: float,
) -> float:
    """Calculate IV Percentile (IVP) — percentage of days where IV was below current.

    Args:
        iv_history: List of historical daily IV values (at least 2 entries).
        current_iv: Current implied volatility (decimal).

    Returns:
        IVP value in the range [0, 100].
    """
    if not iv_history:
        return 0.0
    days_below = sum(1 for iv in iv_history if iv < current_iv)
    ivp = days_below / len(iv_history) * 100.0
    return round(ivp, 2)


# ---------------------------------------------------------------------------
# Portfolio Greeks dataclass
# ---------------------------------------------------------------------------


@dataclass
class PortfolioGreeks:
    """Aggregate Greeks across all options positions in the portfolio."""

    total_delta: float = 0.0
    total_gamma: float = 0.0
    total_theta: float = 0.0
    total_vega: float = 0.0
    total_rho: float = 0.0
    position_count: int = 0
    as_of: datetime = field(default_factory=datetime.utcnow)

    def __str__(self) -> str:
        return (
            f"Portfolio Greeks ({self.position_count} positions) | "
            f"Δ {self.total_delta:+.4f}  Γ {self.total_gamma:.4f}  "
            f"Θ {self.total_theta:+.4f}/day  V {self.total_vega:.4f}  "
            f"ρ {self.total_rho:.4f}"
        )


# ---------------------------------------------------------------------------
# Greeks alert dataclass
# ---------------------------------------------------------------------------


@dataclass
class GreeksAlert:
    """Alert raised when a Greeks threshold is breached."""

    position_id: str
    symbol: str
    strategy: str
    alert_type: str  # e.g. "DELTA_BREACH", "GAMMA_SPIKE"
    message: str
    delta: float
    threshold: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Greeks Monitor
# ---------------------------------------------------------------------------


class GreeksMonitor:
    """Real-time Greeks monitor for an options portfolio.

    Tracks the Greeks of all open positions and raises alerts when
    configurable thresholds are breached — most importantly, when the
    delta on a *short* strike exceeds the roll-alert threshold (default 0.30).

    Usage::

        monitor = GreeksMonitor(delta_alert_threshold=0.30)
        monitor.update_position("pos-001", "MES", "COVERED_CALL", greeks_dict, "short")
        alerts = monitor.check_alerts()
    """

    def __init__(
        self,
        delta_alert_threshold: float = 0.30,
        gamma_alert_threshold: float = 0.05,
    ) -> None:
        """
        Args:
            delta_alert_threshold: Absolute delta on short strikes that triggers
                a roll alert (default 0.30).
            gamma_alert_threshold: Gamma threshold that triggers a spike alert.
        """
        self.delta_alert_threshold = delta_alert_threshold
        self.gamma_alert_threshold = gamma_alert_threshold

        # position_id → {"symbol", "strategy", "greeks", "leg_type"}
        self._positions: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def update_position(
        self,
        position_id: str,
        symbol: str,
        strategy: str,
        greeks: dict[str, float],
        leg_type: Literal["long", "short"] = "short",
    ) -> None:
        """Register or update a position's Greeks snapshot.

        Args:
            position_id: Unique position identifier.
            symbol:      Underlying ticker (e.g. ``"MES"``).
            strategy:    Strategy name (e.g. ``"COVERED_CALL"``).
            greeks:      Dict as returned by :func:`calculate_greeks`.
            leg_type:    Whether this leg is ``"long"`` or ``"short"``.
        """
        self._positions[position_id] = {
            "symbol": symbol,
            "strategy": strategy,
            "greeks": greeks,
            "leg_type": leg_type,
            "updated_at": datetime.utcnow(),
        }

    def remove_position(self, position_id: str) -> None:
        """Remove a closed position from tracking."""
        self._positions.pop(position_id, None)

    def clear(self) -> None:
        """Remove all tracked positions."""
        self._positions.clear()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_portfolio_greeks(self) -> PortfolioGreeks:
        """Aggregate Greeks across all tracked positions.

        Returns:
            :class:`PortfolioGreeks` with summed delta, gamma, theta, vega, rho.
        """
        pg = PortfolioGreeks(position_count=len(self._positions))
        for pos in self._positions.values():
            g = pos["greeks"]
            sign = -1.0 if pos["leg_type"] == "short" else 1.0
            pg.total_delta += sign * g.get("delta", 0.0)
            pg.total_gamma += sign * g.get("gamma", 0.0)
            pg.total_theta += sign * g.get("theta", 0.0)
            pg.total_vega += sign * g.get("vega", 0.0)
            pg.total_rho += sign * g.get("rho", 0.0)

        pg.total_delta = round(pg.total_delta, 6)
        pg.total_gamma = round(pg.total_gamma, 6)
        pg.total_theta = round(pg.total_theta, 6)
        pg.total_vega = round(pg.total_vega, 6)
        pg.total_rho = round(pg.total_rho, 6)
        return pg

    def check_alerts(self) -> list[GreeksAlert]:
        """Evaluate all tracked positions against alert thresholds.

        Returns:
            List of :class:`GreeksAlert` instances (may be empty).
        """
        alerts: list[GreeksAlert] = []

        for pos_id, pos in self._positions.items():
            g = pos["greeks"]
            symbol = pos["symbol"]
            strategy = pos["strategy"]
            leg_type = pos["leg_type"]
            delta = g.get("delta", 0.0)
            gamma = g.get("gamma", 0.0)

            # --- Delta breach on short strikes ---
            if leg_type == "short" and abs(delta) >= self.delta_alert_threshold:
                alerts.append(
                    GreeksAlert(
                        position_id=pos_id,
                        symbol=symbol,
                        strategy=strategy,
                        alert_type="DELTA_BREACH",
                        message=(
                            f"Short strike delta {delta:+.4f} has reached or exceeded "
                            f"roll threshold {self.delta_alert_threshold:.2f}. "
                            f"Consider rolling the position."
                        ),
                        delta=delta,
                        threshold=self.delta_alert_threshold,
                    )
                )
                logger.warning(
                    "[GreeksMonitor] DELTA_BREACH — %s %s pos=%s delta=%+.4f threshold=%.2f",
                    symbol,
                    strategy,
                    pos_id,
                    delta,
                    self.delta_alert_threshold,
                )

            # --- Gamma spike ---
            if abs(gamma) >= self.gamma_alert_threshold:
                alerts.append(
                    GreeksAlert(
                        position_id=pos_id,
                        symbol=symbol,
                        strategy=strategy,
                        alert_type="GAMMA_SPIKE",
                        message=(
                            f"Gamma {gamma:.4f} exceeded spike threshold "
                            f"{self.gamma_alert_threshold:.4f}. "
                            f"High sensitivity to underlying moves near expiry."
                        ),
                        delta=delta,
                        threshold=self.gamma_alert_threshold,
                    )
                )
                logger.warning(
                    "[GreeksMonitor] GAMMA_SPIKE — %s %s pos=%s gamma=%.4f threshold=%.4f",
                    symbol,
                    strategy,
                    pos_id,
                    gamma,
                    self.gamma_alert_threshold,
                )

        return alerts

    def summary(self) -> str:
        """Return a one-line human-readable summary for logging."""
        pg = self.get_portfolio_greeks()
        alerts = self.check_alerts()
        alert_str = f" | {len(alerts)} ALERT(S)" if alerts else ""
        return f"{pg}{alert_str}"
