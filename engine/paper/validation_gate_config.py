"""
Canonical paper validation gate thresholds — aligned with CLAUDE.md / project PRD.

Single source of truth for:
  - Approved paper futures symbols (Tier-1 validation)
  - Numeric gates: PF, Sharpe, win rate, min trades, min days, max drawdown

Routers and ValidationTracker import from here; do not duplicate literals.
"""

from __future__ import annotations

# Tier-1 paper validation (WFE-approved for live paper); not MES/MGC.
APPROVED_PAPER_SYMBOLS: tuple[str, ...] = ("MCL", "MNQ")

# Same targets as CLAUDE.md "Validation gates" (PF >= 2.0, Sharpe >= 1.5, etc.)
PAPER_VALIDATION_GATES: dict[str, float | int] = {
    "profit_factor": 2.0,
    "sharpe_ratio": 1.5,
    "win_rate_pct": 55.0,
    "min_trades": 60,
    "min_days": 30,
    "max_drawdown_pct": 15.0,
}
