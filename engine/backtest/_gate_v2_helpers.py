"""Shared gate v2 metric helpers — single source of truth for runner files."""
from __future__ import annotations

import numpy as np


def bootstrap_pf_ci_lower(oos_pfs: list[float], n: int = 5000) -> float:
    """Bootstrap 5th-percentile of mean PF distribution; inf-cap baked in."""
    # Cap inf/-inf before bootstrapping — np.percentile returns NaN via inf-inf interpolation
    capped = [min(max(pf, 0.0), 5.0) if not (pf == float("inf") or pf == float("-inf"))
              else (5.0 if pf == float("inf") else 0.0)
              for pf in oos_pfs]
    if len(capped) < 2:
        return float(np.mean(capped)) if capped else 0.0
    rng = np.random.default_rng(42)
    arr = np.array(capped, dtype=float)
    boot_means = [rng.choice(arr, size=len(arr), replace=True).mean() for _ in range(n)]
    return float(np.percentile(boot_means, 5.0))


def classify_wfo_consistency(oos_pfs: list[float]) -> str:
    """Classify WFO consistency: STRONG >= 75% profitable windows, MODERATE >= 55%."""
    if not oos_pfs:
        return "WEAK"
    pct = sum(1 for pf in oos_pfs if pf > 1.0) / len(oos_pfs)
    if pct >= 0.75:
        return "STRONG"
    if pct >= 0.55:
        return "MODERATE"
    return "WEAK"
