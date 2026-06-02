"""
Canonical paper validation gate thresholds — aligned with CLAUDE.md / project PRD.

Single source of truth for:
  - Approved paper futures symbols (Tier-1 validation)
  - Numeric gates: PF, Sharpe, win rate, min trades, min days, max drawdown

Routers and ValidationTracker import from here; do not duplicate literals.
"""

from __future__ import annotations

# Tier-1 paper validation (WFE-approved for live paper).
# MES added 2026-05-05: gate v2 ALT PASS (dsr=0.667, rolling_wfo=STRONG),
# SMA(50,200)+2.0×ATR, verdict file: data/gate_v2_verdicts/MES_trend_rank7.json
APPROVED_PAPER_SYMBOLS: tuple[str, ...] = ("MCL", "MNQ", "MES")

# Same targets as CLAUDE.md "Validation gates" (PF >= 2.0, Sharpe >= 1.5, etc.)
PAPER_VALIDATION_GATES: dict[str, float | int] = {
    "profit_factor": 2.0,
    "sharpe_ratio": 1.5,
    "win_rate_pct": 55.0,
    "min_trades": 60,
    "min_days": 30,
    "max_drawdown_pct": 15.0,
}

# ---------------------------------------------------------------------------
# Execution-fidelity gate (ADDITIVE — does NOT replace PAPER_VALIDATION_GATES)
# ---------------------------------------------------------------------------
# Rationale: statistical EDGE is proven by the walk-forward / gate-v2 analysis on
# 2+ years of out-of-sample data (see engine/data/gate_v2_verdicts/). Re-proving
# edge from paper accrual (PAPER_VALIDATION_GATES: 60 trades / PF>=2.0) takes
# ~15-30 years at the proven strategies' ~3-6 trades/yr pace.
#
# These thresholds answer a DIFFERENT, narrower question: does LIVE execution
# match the backtest's assumptions (slippage, fill price, broker connectivity)?
# That needs a small sample of REAL broker fills, not 60. See
# docs/TRADE_SYSTEM_SCOPE_AND_ROADMAP.md Part 4.
#
# IMPORTANT: this dict and the /validate/execution-fidelity endpoint are ADVISORY
# instrumentation only. They gate NOTHING. They do not alter live_readiness.py or
# phase3_criteria.py. Substituting fidelity for the edge gate in the live-readiness
# VERDICT is a separate [safety-review] change requiring explicit approval AND the
# IBKR order path being enabled (ALLOW_PAPER_SIMULATED_ORDERS=True) so real fills
# exist to measure. Until then, fidelity measured on simulated paper_trades is
# self-referential and reported as such.
EXECUTION_FIDELITY_GATES: dict[str, float | int] = {
    "min_fills": 15,                 # sample size for fidelity confidence (not edge)
    "max_avg_slippage_ticks": 1.5,   # avg fill slippage vs signal price
    "min_realized_pf_floor": 1.0,    # PF sign-check ONLY (not the 2.0 edge gate)
}
