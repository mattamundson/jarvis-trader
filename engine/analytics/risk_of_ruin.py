"""
Risk-of-Ruin Monte Carlo
========================
Parametric Monte Carlo that estimates the probability of tripping the
drawdown kill switch ("ruin" for the trading phase) under fixed-fractional
position sizing, using the ACTUAL kill-switch thresholds from the risk config.

Motivation: the -20% drawdown halt and a high per-trade risk fraction are not
independent knobs. At large ``risk_pct`` the ordinary variance of a *positive*
edge produces a 20% peak-to-trough drawdown almost surely within a quarter, so
the kill switch flips from a tail-risk backstop into a near-certain halt. This
module quantifies that so the per-trade fraction can be reconciled with the
drawdown limit rather than set blind.

Standalone by design — thresholds default to the aggressive $10K profile but can
be passed explicitly; no hard dependency on pydantic/config so it runs in a
lightweight venv and in tests. Diagnostic only; changes no trade authorization.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

# Defaults mirror engine/config.py aggressive profile (Amo-confirmed 2026-06-25).
# engine/.env overrides config at runtime; these are the code-default magnitudes.
DEFAULT_CAPITAL = 10_000.0
DEFAULT_DAILY_HALT = 0.06     # MAX_DAILY_LOSS_PCT
DEFAULT_DD_KILL = 0.20        # MAX_DRAWDOWN_PCT (emergency halt from equity peak)


@dataclass(frozen=True)
class RuinResult:
    """One (edge, risk) cell of the risk-of-ruin sweep."""

    win_rate: float
    payoff_r: float
    risk_pct: float
    ruin_prob: float
    median_equity: float
    p5_equity: float
    p95_equity: float


def simulate_path(
    win_rate: float,
    payoff_r: float,
    risk_pct: float,
    rng: np.random.Generator,
    *,
    capital: float = DEFAULT_CAPITAL,
    daily_halt: float = DEFAULT_DAILY_HALT,
    dd_kill: float = DEFAULT_DD_KILL,
    trades_per_day: int = 3,
    horizon_days: int = 84,
) -> tuple[bool, float]:
    """Simulate one equity path. Returns (ruined, terminal_equity).

    ``ruined`` is True when equity falls to ``dd_kill`` below its running peak
    (the kill switch halts the phase). Fixed-fractional sizing on CURRENT equity;
    a day stops early once its P&L reaches ``-daily_halt``.
    """
    eq = peak = capital
    for _ in range(horizon_days):
        day_start = eq
        for _ in range(trades_per_day):
            risk_amt = risk_pct * eq
            eq += payoff_r * risk_amt if rng.random() < win_rate else -risk_amt
            peak = max(peak, eq)
            if eq <= peak * (1.0 - dd_kill):
                return True, eq
            if eq <= day_start * (1.0 - daily_halt):
                break
    return False, eq


def estimate_ruin(
    win_rate: float,
    payoff_r: float,
    risk_pct: float,
    *,
    n_paths: int = 40_000,
    seed: int = 12345,
    **path_kwargs,
) -> RuinResult:
    """Monte Carlo risk-of-ruin for one (edge, risk) cell."""
    rng = np.random.default_rng(seed)
    ruins = 0
    terms = np.empty(n_paths)
    for i in range(n_paths):
        ruined, term = simulate_path(win_rate, payoff_r, risk_pct, rng, **path_kwargs)
        ruins += ruined
        terms[i] = term
    return RuinResult(
        win_rate=win_rate,
        payoff_r=payoff_r,
        risk_pct=risk_pct,
        ruin_prob=ruins / n_paths,
        median_equity=float(np.median(terms)),
        p5_equity=float(np.percentile(terms, 5)),
        p95_equity=float(np.percentile(terms, 95)),
    )


# Representative edge scenarios (label, win_rate, payoff_r), negative -> strong trend.
DEFAULT_SCENARIOS = [
    ("negative edge (WR45/R1.0)", 0.45, 1.0),
    ("break-even (WR50/R1.0)", 0.50, 1.0),
    ("slight edge (WR50/R1.2)", 0.50, 1.2),
    ("trend edge (WR42/R1.8)", 0.42, 1.8),
    ("strong trend (WR40/R2.5)", 0.40, 2.5),
]
DEFAULT_RISK_LEVELS = (0.01, 0.02, 0.03)


def sweep(
    scenarios=DEFAULT_SCENARIOS,
    risk_levels=DEFAULT_RISK_LEVELS,
    *,
    n_paths: int = 40_000,
    **path_kwargs,
) -> list[tuple[str, RuinResult]]:
    """Run the full (scenario x risk) grid. Returns [(label, RuinResult), ...]."""
    out = []
    for label, wr, r in scenarios:
        for rp in risk_levels:
            out.append((label, estimate_ruin(wr, r, rp, n_paths=n_paths, **path_kwargs)))
    return out


def format_table(rows: list[tuple[str, RuinResult]]) -> str:
    """Human-readable table for a sweep result."""
    header = f"{'scenario':28s} {'risk':>5s} {'ruin%':>7s} {'medEq':>9s} {'p5Eq':>9s} {'p95Eq':>9s}"
    lines = [header, "-" * len(header)]
    for label, r in rows:
        lines.append(
            f"{label:28s} {r.risk_pct:5.0%} {r.ruin_prob:7.1%} "
            f"{r.median_equity:9,.0f} {r.p5_equity:9,.0f} {r.p95_equity:9,.0f}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    print(format_table(sweep()))
