"""
JARVIS TRADER — Chetan Gap Finder
Port of ``thinkorswim-scripts/GAPS_Chetan1STUDY.ts`` (Chetan variant).
Spec: ``thinkorswim-scripts/docs/gaps_chetan.md``

CROSS-ASSET DEPENDENCY DROPPED:
The original ThinkScript fetches ``close("HYG")`` and ``close("SPX")`` to
compute 2-bar diffs (hyg_diff / spx_diff) and uses their divergence
(HYG falling, SPX rising) to flag early gap candidates.  JARVIS receives a
single OHLCV DataFrame per instrument; there is no bundled HYG feed.
The HYG/SPX divergence check is therefore NOT reproduced here.  Only the
price-bar gap detection logic is ported.

The VIX / /VX commented-out branch in the .ts is also omitted — it was
never activated in the original study.

Gap logic (directly from .ts line 5):
    Gap DOWN  : low[1]  - high   >  min_gap_points  (prior low above current high)
    Gap UP    : low     - high[1] >= min_gap_points  (current low above prior high)
    NONE      : neither condition met
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_chetan_gaps(
    df: pd.DataFrame,
    min_gap_points: float = 0.10,
    direction_threshold_pct: float = 0.001,
) -> pd.DataFrame:
    """Detect intraday price gaps using the Chetan ThinkScript logic.

    Parameters
    ----------
    df:
        OHLCV DataFrame with columns ``high``, ``low``, ``open``, ``close``.
        Index may be DatetimeIndex or RangeIndex.
    min_gap_points:
        Minimum gap size in price points to qualify as a structural gap.
        Default 0.10, matching the fixed threshold in the original .ts.
    direction_threshold_pct:
        Unused by the core gap logic; reserved for future HYG/SPX divergence
        integration.  Kept in the signature so callers can pass it without
        breakage once cross-asset data is available.

    Returns
    -------
    pd.DataFrame
        Original DataFrame with four new columns appended:

        ``chetan_gap_detected``  bool  — True when a qualifying gap is present.
        ``chetan_gap_direction`` str   — 'UP', 'DOWN', or 'NONE'.
        ``chetan_gap_top``       float — Upper bound of gap zone (NaN when no gap).
        ``chetan_gap_bottom``    float — Lower bound of gap zone (NaN when no gap).

    Notes
    -----
    Cross-asset HYG/SPX divergence from the original .ts is NOT computed.
    The colour-assignment analogue maps as: CYAN → 'DOWN', ORANGE → 'UP'.

    ThinkorSwim ThinkScript reference (line 5)::

        AssignPriceColor(
            if (low[1] - high) > 0.10 then Color.CYAN      # gap DOWN
            else if (high[1] - low) < 0.10 then Color.ORANGE   # gap UP (negative value)
            else Color.GRAY
        );

    The second branch ``(high[1] - low) < 0.10`` is ambiguous because it also
    matches small positive overlaps.  Per the spec table
    (``gaps_chetan.md`` §JARVIS Mapping) the intended gap-up condition is
    ``low - prior_high >= min_gap_points``; this implementation follows the
    spec intent rather than the literal loose threshold.
    """
    out = df.copy()

    high = out["high"]
    low = out["low"]

    prior_low = low.shift(1)
    prior_high = high.shift(1)

    gap_down_magnitude = prior_low - high        # positive when gap-down exists
    gap_up_magnitude = low - prior_high          # positive when gap-up exists

    is_gap_down = gap_down_magnitude >= min_gap_points
    is_gap_up = gap_up_magnitude >= min_gap_points

    direction = np.where(is_gap_down, "DOWN", np.where(is_gap_up, "UP", "NONE"))

    gap_top = np.where(
        is_gap_down, prior_low.values,
        np.where(is_gap_up, low.values, np.nan),
    )
    gap_bottom = np.where(
        is_gap_down, high.values,
        np.where(is_gap_up, prior_high.values, np.nan),
    )

    out["chetan_gap_detected"] = is_gap_down | is_gap_up
    out["chetan_gap_direction"] = direction
    out["chetan_gap_top"] = gap_top.astype(float)
    out["chetan_gap_bottom"] = gap_bottom.astype(float)

    return out
