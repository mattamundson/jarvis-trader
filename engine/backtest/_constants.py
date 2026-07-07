"""
Shared constants for all backtest runner scripts.

Centralised here so gate-tuning only requires one edit.

Do NOT import this module from _gate_v2_helpers.py — that file is imported
by runners too and a cross-dependency would create a circular import.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# ALT-gate thresholds — identical across all runners
# ---------------------------------------------------------------------------

#: Minimum fixed-params profit-factor required by the ALT gate path.
GATE_FIXED_PARAMS_MIN_PF: float = 1.20

#: WFO consistency ratings accepted by the ALT gate ("MODERATE" or better).
GATE_WFO_CONSISTENCY_VALUES: list[str] = ["MODERATE", "STRONG"]

# ---------------------------------------------------------------------------
# Cost-sweep tier ordering — same in every runner
# ---------------------------------------------------------------------------

#: Ordered tier names from best (cheapest) to worst (most expensive).
#: Runners use this to iterate cost assumptions in ascending cost order.
COST_TIER_ORDER: list[str] = ["optimistic", "realistic", "pessimistic", "catastrophic"]
