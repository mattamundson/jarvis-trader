"""H1/H2 chronological stationarity gate.

WHY THIS MODULE EXISTS
----------------------
The gate's moving-block bootstrap PF-CI is computed on the POOLED OOS trade
series. Pooling is blind to WHEN the edge happened: a strategy that loses across
the first half of the sample and makes 100% of its profit in the second half
pools to a great-looking PF-CI and passes. The canonical campaign example is the
ES-NQ spread -- chronologically H1 PF 0.91 (a net loser) / H2 PF 7.96. A pooled
gate would authorize an edge that only worked recently; forward, it is far more
likely to be a regime artifact than a durable edge.

The campaign re-learned this lesson ad-hoc, per runner. This module centralises
the check so every gate path shares one tested implementation: split the
chronologically-ordered OOS trades in half and require BOTH halves to be
profitable (each with enough trades to mean anything). It is deliberately simple
-- two PFs and an AND -- because a stationarity check that is itself overfit
defeats the purpose.

UNITS: takes per-trade PnLs (USD) already in chronological order. The companion
`_gate_v2_trade_metrics.concat_oos_trade_pnls` produces exactly that ordering
(per-window in sequence, empty windows contributing nothing).
"""

from __future__ import annotations

from typing import Sequence


def _profit_factor(pnls: Sequence[float]) -> float:
    """Gross wins / gross losses. +inf when there are wins and no losses; 0.0
    when the slice is empty or has no wins."""
    wins = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)  # positive magnitude
    if losses <= 0:
        return float("inf") if wins > 0 else 0.0
    return float(wins) / float(losses)


def h1_h2_split(
    pnls: Sequence[float],
    min_trades_per_half: int = 5,
    min_pf: float = 1.0,
) -> dict:
    """Chronological first-half/second-half PF consistency check.

    Args:
        pnls: per-trade PnLs in chronological order.
        min_trades_per_half: each half must hold at least this many trades for
            the split to carry evidence (default-deny below it).
        min_pf: profit-factor floor each half must clear (default 1.0 = "must
            not lose money"; raise to e.g. 1.10 for a stricter edge floor).

    Returns dict with h1_pf, h2_pf, h1_n, h2_n, min_half_pf, both_profitable,
    sample_adequate, consistent, plus the thresholds used. `consistent` is the
    single boolean a gate consumes: True iff both halves clear `min_pf` AND each
    half has >= `min_trades_per_half` trades.
    """
    pnls = list(pnls)
    n = len(pnls)
    mid = n // 2
    h1, h2 = pnls[:mid], pnls[mid:]

    h1_pf = _profit_factor(h1)
    h2_pf = _profit_factor(h2)
    sample_adequate = len(h1) >= min_trades_per_half and len(h2) >= min_trades_per_half
    both_profitable = h1_pf >= min_pf and h2_pf >= min_pf
    consistent = bool(sample_adequate and both_profitable)

    # min_half_pf: the weaker half, capped-finite for readable reason strings.
    min_half_pf = min(h1_pf, h2_pf)

    return {
        "h1_pf": round(h1_pf, 6) if h1_pf != float("inf") else float("inf"),
        "h2_pf": round(h2_pf, 6) if h2_pf != float("inf") else float("inf"),
        "h1_n": len(h1),
        "h2_n": len(h2),
        "min_half_pf": round(min_half_pf, 6) if min_half_pf != float("inf") else float("inf"),
        "both_profitable": bool(both_profitable),
        "sample_adequate": bool(sample_adequate),
        "consistent": consistent,
        "min_pf": float(min_pf),
        "min_trades_per_half": int(min_trades_per_half),
    }
