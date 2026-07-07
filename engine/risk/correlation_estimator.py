"""Pairwise return-correlation estimation for correlation-aware sizing (P2.3).

Produces the sparse ``{(a, b): rho}`` map that
``risk.portfolio_sizer.correlation_scale_factor`` consumes, from per-symbol
return series (derivable from cached bars upstream). Pure stdlib — no pandas in
the sizing hot path — so it is fast and fully unit-testable.

Design choices:
  - Unequal-length series are aligned on their most-recent overlapping tail
    (same-interval bars pulled toward "now" line up at the right edge).
  - A pair is OMITTED (not defaulted to 0) when overlap < ``min_overlap`` or
    either leg has zero variance. The sizer falls back to its conservative
    ``default_corr`` for omitted pairs, so "unknown" never silently reads as
    "uncorrelated".
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Optional


def pearson(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    """Pearson correlation of two equal-length series, or None if undefined.

    Returns None when fewer than 2 points or either series has zero variance.
    Clamped to [-1, 1] to absorb floating-point overshoot.
    """
    n = min(len(x), len(y))
    if n < 2:
        return None
    mx = sum(x[:n]) / n
    my = sum(y[:n]) / n
    sxy = sxx = syy = 0.0
    for i in range(n):
        dx = x[i] - mx
        dy = y[i] - my
        sxy += dx * dy
        sxx += dx * dx
        syy += dy * dy
    if sxx <= 0.0 or syy <= 0.0:
        return None
    rho = sxy / math.sqrt(sxx * syy)
    if rho < -1.0:
        return -1.0
    if rho > 1.0:
        return 1.0
    return rho


def estimate_correlations(
    returns_by_symbol: Mapping[str, Sequence[float]],
    min_overlap: int = 20,
    default_corr: float = 0.0,  # accepted for signature symmetry; omitted pairs use it downstream
) -> dict[tuple[str, str], float]:
    """Return ``{(a, b): rho}`` for every symbol pair with a defined correlation.

    Pairs with overlap < ``min_overlap`` or a zero-variance leg are omitted.
    """
    symbols = sorted(returns_by_symbol)
    out: dict[tuple[str, str], float] = {}
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            a, b = symbols[i], symbols[j]
            xs = returns_by_symbol[a]
            ys = returns_by_symbol[b]
            n = min(len(xs), len(ys))
            if n < min_overlap:
                continue
            # Align on the overlapping tail (most-recent n points of each).
            xa = list(xs)[-n:]
            ya = list(ys)[-n:]
            rho = pearson(xa, ya)
            if rho is None:
                continue
            out[(a, b)] = rho
    return out


def bars_to_returns(closes: Sequence[float]) -> list[float]:
    """Simple close-to-close returns from a price series (helper for callers)."""
    rets: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev:
            rets.append((closes[i] - prev) / prev)
    return rets
