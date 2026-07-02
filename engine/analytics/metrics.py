"""Canonical server-side performance metrics — single source of truth.

Pure functions that compute drawdown / Calmar / Sharpe / total-return, encoding
the floor + guard invariants established by PR #272 (fix/portfolio-metrics-integrity).
No I/O, no DB, no globals. Endpoints and the dashboard DISPLAY these values; they
must never recompute them.

Invariants (each guard traces to a real blowup PR #272 fixed):
  * Drawdown denominator is floored against starting capital: a cumulative-P&L
    curve that never rises above its start cannot divide by a ~1e-9 peak and emit
    nonsense like -1.46e14. (portfolio_router seeded peak at 0 + guarded peak > 0;
    flooring against starting capital is the stronger, canonical form.)
  * max_dd is floored before Calmar: below the floor Calmar is undefined (returns
    None) rather than exploding as return / ~0.
  * Sharpe guards a near-zero denominator -> None (never NaN/inf).
  * total_return_pct floors the denominator against starting capital.

Every function returns None on a degenerate input rather than NaN or an absurd
finite number. Callers render None as "n/a", never as a live figure.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

# max_dd magnitudes below this are treated as "no meaningful drawdown" for Calmar.
# Dividing an annual return by a ~0 drawdown is the -1e14 blowup PR #272 killed.
_MIN_MAX_DD_FOR_CALMAR = 1e-6
# Below this the Sharpe denominator (return std-dev) is treated as zero.
_EPS = 1e-12

__all__ = [
    "max_drawdown_pct",
    "calmar",
    "sharpe",
    "total_return_pct",
]


def max_drawdown_pct(
    equity_curve: Sequence[float],
    starting_capital: float,
) -> float | None:
    """Max peak-to-trough drawdown as a POSITIVE percentage of the running peak.

    Args:
        equity_curve: ordered sequence of ABSOLUTE account equity levels
            (e.g. ``starting_capital + cumulative_pnl`` per bar/day). ``None``
            entries are skipped.
        starting_capital: the floor for the peak denominator. The peak is seeded
            here so a curve that only ever dips below the start still measures
            drawdown against a trustworthy denominator instead of a ~0 peak.

    Returns:
        Positive drawdown percentage (0.0 when the curve never falls below its
        peak), or ``None`` when ``starting_capital`` is non-positive (no
        meaningful denominator).
    """
    if starting_capital is None or starting_capital <= 0:
        return None
    levels = [float(x) for x in equity_curve if x is not None]
    if not levels:
        return 0.0

    peak = float(starting_capital)  # floor the denominator against starting capital
    max_dd = 0.0
    for eq in levels:
        if eq > peak:
            peak = eq
        # peak >= starting_capital > 0 always holds here -> no divide-by-~0.
        dd = (peak - eq) / peak * 100.0
        if dd > max_dd:
            max_dd = dd
    return round(max_dd, 4)


def calmar(annual_return: float | None, max_dd: float | None) -> float | None:
    """Calmar ratio = annual return / |max drawdown|, with a denominator floor.

    Args:
        annual_return: annualised return (caller-consistent units — dollars,
            fraction, or percent; the result's unit follows ``max_dd``).
        max_dd: max drawdown magnitude (sign-agnostic). Must share units with
            ``annual_return`` for the ratio to be meaningful.

    Returns:
        The ratio, or ``None`` when either input is missing or ``|max_dd|`` is
        below ``_MIN_MAX_DD_FOR_CALMAR`` (denominator too small to trust).
    """
    if annual_return is None or max_dd is None:
        return None
    mdd = abs(float(max_dd))
    if mdd < _MIN_MAX_DD_FOR_CALMAR:
        return None  # floor: undefined below the floor, never a return/~0 blowup
    return round(float(annual_return) / mdd, 4)


def sharpe(
    returns: Sequence[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float | None:
    """Annualised Sharpe ratio from a per-period return series.

    Args:
        returns: per-period returns (e.g. daily P&L buckets). At least two
            non-None values are required for a sample std-dev.
        risk_free_rate: annualised risk-free rate subtracted from the annualised
            return (same units as the annualised return).
        periods_per_year: annualisation factor (252 trading days by default).

    Returns:
        The annualised Sharpe ratio, or ``None`` when there are < 2 observations
        or the return std-dev is ~0 (near-zero denominator guard).
    """
    vals = [float(r) for r in returns if r is not None]
    n = len(vals)
    if n < 2:
        return None
    mean = sum(vals) / n
    variance = sum((r - mean) ** 2 for r in vals) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std <= _EPS:
        return None  # zero-variance series has no defined risk-adjusted return
    annual_return = mean * periods_per_year
    annual_std = std * math.sqrt(periods_per_year)
    return round((annual_return - risk_free_rate) / annual_std, 4)


def total_return_pct(
    ending_equity: float,
    starting_capital: float,
) -> float | None:
    """Total return as a percentage of starting capital.

    Args:
        ending_equity: final absolute account equity.
        starting_capital: the denominator; must be positive.

    Returns:
        Percent return, or ``None`` when ``starting_capital`` is non-positive
        (no meaningful denominator).
    """
    if starting_capital is None or starting_capital <= 0:
        return None
    return round(
        (float(ending_equity) - float(starting_capital)) / float(starting_capital) * 100.0,
        4,
    )
