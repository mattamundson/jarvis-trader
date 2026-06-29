"""Correlation-aware portfolio sizing (P2.3).

The per-instrument sizer (``risk.position_sizer.calculate_position_size``) sizes
each symbol independently, so two correlated positions can stack aggregate risk
beyond what either limit implies. This module supplies the missing portfolio
view as pure functions:

  - ``portfolio_risk``           combined risk across a book, accounting for the
                                 pairwise correlation structure. Uncorrelated
                                 positions add in quadrature; perfectly correlated
                                 ones add linearly; an equal-and-opposite hedge
                                 cancels toward zero.
  - ``correlation_scale_factor`` the multiplicative trim (0..1] to apply to a NEW
                                 position's risk so the combined correlated risk
                                 of (existing book + new) stays at/under a ceiling.
                                 This is the "size MES down when MGC is already
                                 hot" behaviour, derived rather than hand-tuned.

The functions take plain risk *contributions* (e.g. dollar-risk-at-stop or a
risk fraction) and a sparse correlation map keyed by symbol pair. They perform
no I/O and read no live state — pulling the open book / estimating the
correlation matrix / applying the factor to a ``PositionSize`` is the wiring
step, intentionally kept separate (and Amo-gated) so this module stays inert
until a backtest validates the behaviour change.

``scale_factor`` composes multiplicatively with the existing drawdown scale, so
wiring is later a single ``contracts = floor(contracts * corr_factor)`` style
multiply at the sizing seam.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Optional

# A symbol's correlation with itself is 1.0; unknown off-diagonal pairs fall back
# to this default at the call sites that accept one.
_SELF_CORRELATION = 1.0


def _pair_correlation(
    a: str,
    b: str,
    correlations: Mapping[tuple[str, str], float],
    default_corr: float,
) -> float:
    """Symmetric correlation lookup. rho(x,x)=1; unknown pairs => default_corr."""
    if a == b:
        return _SELF_CORRELATION
    if (a, b) in correlations:
        return correlations[(a, b)]
    if (b, a) in correlations:
        return correlations[(b, a)]
    return default_corr


def portfolio_risk(
    risk_contribs: Mapping[str, float],
    correlations: Mapping[tuple[str, str], float],
    default_corr: float = 0.0,
) -> float:
    """Return the combined risk of a book given its correlation structure.

    risk = sqrt( sum_i sum_j r_i * r_j * rho_ij )   with rho_ii = 1.

    A negative term from a hedge can drive the sum below zero numerically; it is
    clamped at zero before the square root (a fully/over-hedged book has no net
    risk, not an imaginary one).
    """
    symbols = list(risk_contribs)
    total = 0.0
    for a in symbols:
        ra = risk_contribs[a]
        for b in symbols:
            rb = risk_contribs[b]
            total += ra * rb * _pair_correlation(a, b, correlations, default_corr)
    if total <= 0.0:
        return 0.0
    return math.sqrt(total)


def correlation_scale_factor(
    new_symbol: str,
    new_risk: float,
    existing_risks: Mapping[str, float],
    correlations: Mapping[tuple[str, str], float],
    max_portfolio_risk: float,
    default_corr: float = 0.0,
) -> float:
    """Trim factor in [0, 1] for a NEW position so combined risk fits the ceiling.

    Let R_e = portfolio_risk(existing). Adding the new position at fraction f of
    its risk r_n gives a combined variance:

        V(f) = R_e^2 + 2 * f * r_n * cov + f^2 * r_n^2

    where ``cov = sum_j rho(new, j) * r_j`` is the new position's covariance with
    the existing book per unit of its own risk. We return the largest f in [0, 1]
    with V(f) <= C^2 (C = max_portfolio_risk):

      - V(1) <= C^2            -> 1.0  (fits at full size, no trim)
      - otherwise solve a*f^2 + b*f + c = 0 for the positive root, clamp to [0,1].
    """
    if new_risk <= 0.0:
        return 1.0
    if max_portfolio_risk <= 0.0:
        return 0.0

    ceiling_sq = max_portfolio_risk * max_portfolio_risk
    r_existing_sq = portfolio_risk(existing_risks, correlations, default_corr) ** 2

    cov = 0.0
    for sym, r in existing_risks.items():
        cov += _pair_correlation(new_symbol, sym, correlations, default_corr) * r

    # Combined variance at full size (f = 1).
    v_full = r_existing_sq + 2.0 * new_risk * cov + new_risk * new_risk
    if v_full <= ceiling_sq:
        return 1.0

    # Solve a f^2 + b f + c = 0 for the maximal feasible f.
    a = new_risk * new_risk
    b = 2.0 * new_risk * cov
    c = r_existing_sq - ceiling_sq

    disc = b * b - 4.0 * a * c
    if disc <= 0.0:
        # No real headroom (existing book already at/over the ceiling, or the
        # cross term leaves no feasible positive f) -> block the new position.
        return 0.0

    f = (-b + math.sqrt(disc)) / (2.0 * a)
    if f <= 0.0:
        return 0.0
    if f >= 1.0:
        return 1.0
    return f


def correlation_trim_contracts(
    symbol: str,
    contracts: int,
    new_risk: float,
    open_book_risks: Mapping[str, float],
    correlations: Mapping[tuple[str, str], float],
    max_portfolio_risk: float,
    default_corr: float = 0.5,
    block_threshold: float = 0.5,
) -> tuple[int, float, str]:
    """Apply the correlation scale factor to an integer micro-contract count.

    Returns ``(trimmed_contracts, factor, reason)``. Risk *policy* lives in the
    two thresholds, kept explicit and conservative because they shape live
    behaviour and should be informed by validation, not buried:

      - ``default_corr`` (0.5): correlation assumed for pairs absent from the
        estimated matrix — biases toward caution (more trim), never less.
      - ``block_threshold`` (0.5): if less than this fraction of the new
        position's risk fits, the book is too full/correlated and the add is
        blocked (0 contracts) rather than shaved to a token size.

    Above the block threshold the size is scaled but floored at 1 contract, so a
    mild correlation does not silently zero out a 1-lot micro signal. Never
    raises on normal inputs; never increases the contract count.
    """
    if contracts <= 0 or new_risk <= 0.0 or not open_book_risks:
        return contracts, 1.0, "no open book — no correlation trim"

    factor = correlation_scale_factor(
        symbol, new_risk, open_book_risks, correlations, max_portfolio_risk, default_corr
    )
    if factor >= 1.0:
        return contracts, 1.0, "room available — no correlation trim"
    if factor < block_threshold:
        return (
            0,
            factor,
            (
                f"correlation block x{factor:.3f} < {block_threshold:.2f} "
                f"(book {sorted(open_book_risks)} too full/correlated)"
            ),
        )
    trimmed = max(1, round(contracts * factor))
    return (
        trimmed,
        factor,
        (
            f"correlation trim x{factor:.3f}: {contracts} -> {trimmed} "
            f"(book {sorted(open_book_risks)})"
        ),
    )


def combined_scale(*factors: Optional[float]) -> float:
    """Multiply scale factors (e.g. drawdown * correlation), ignoring None.

    Convenience for the eventual wiring seam: a correlation trim composes with
    the existing drawdown scale by multiplication, never by replacement.
    """
    result = 1.0
    for fac in factors:
        if fac is None:
            continue
        result *= fac
    return max(0.0, min(1.0, result))
