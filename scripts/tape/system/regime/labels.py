"""Session labels: trend day vs balance day (plus ambiguous).

Primary definitions (task brief):
  Trend: close in outer 20% of RTH range AND range >= 1.2x 20-day avg range,
         OR one-sided IB breakout by >= 1x IB range.
  Balance: close within IB OR middle 50% of range, AND range < 1x 20-day avg.
  Else: ambiguous.

Sensitivity variants tweak the close-location and range multipliers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LabelParams:
    outer_frac: float = 0.20          # close in outer X% of range
    trend_range_mult: float = 1.2     # vs 20d avg range
    balance_mid_frac: float = 0.50    # middle fraction for balance close
    balance_range_mult: float = 1.0   # range must be under this * avg
    ib_breakout_mult: float = 1.0     # one-sided IB extension vs IB range
    name: str = "primary"


VARIANTS = [
    LabelParams(),  # primary
    LabelParams(outer_frac=0.15, trend_range_mult=1.3, name="strict_trend"),
    LabelParams(outer_frac=0.25, trend_range_mult=1.1, name="loose_trend"),
    LabelParams(balance_mid_frac=0.60, balance_range_mult=0.9, name="strict_balance"),
    LabelParams(balance_mid_frac=0.40, balance_range_mult=1.1, name="loose_balance"),
]


def close_position(low: float, high: float, close: float) -> Optional[float]:
    """0 = close at low, 1 = close at high. None if range is zero."""
    rng = high - low
    if rng <= 0:
        return None
    return (close - low) / rng


def label_session(
    *,
    rth_low: float,
    rth_high: float,
    rth_close: float,
    avg_range_20: float,
    ib_low: Optional[float],
    ib_high: Optional[float],
    params: LabelParams = LabelParams(),
) -> str:
    """Return 'trend' | 'balance' | 'ambiguous'."""
    rng = rth_high - rth_low
    if rng <= 0 or avg_range_20 <= 0:
        return "ambiguous"

    pos = close_position(rth_low, rth_high, rth_close)
    if pos is None:
        return "ambiguous"

    outer = pos <= params.outer_frac or pos >= (1.0 - params.outer_frac)
    wide = rng >= params.trend_range_mult * avg_range_20

    breakout = False
    if ib_low is not None and ib_high is not None:
        ib_rng = ib_high - ib_low
        if ib_rng > 0:
            up = rth_high - ib_high
            dn = ib_low - rth_low
            thresh = params.ib_breakout_mult * ib_rng
            # one side only
            if (up >= thresh and dn < thresh) or (dn >= thresh and up < thresh):
                breakout = True

    is_trend = (outer and wide) or breakout

    mid_lo = 0.5 - params.balance_mid_frac / 2.0
    mid_hi = 0.5 + params.balance_mid_frac / 2.0
    in_mid = mid_lo <= pos <= mid_hi
    in_ib = (
        ib_low is not None
        and ib_high is not None
        and ib_low <= rth_close <= ib_high
    )
    narrow = rng < params.balance_range_mult * avg_range_20
    is_balance = narrow and (in_mid or in_ib)

    if is_trend and is_balance:
        # Prefer trend when both fire (rare; usually wide + mid close conflict).
        return "trend"
    if is_trend:
        return "trend"
    if is_balance:
        return "balance"
    return "ambiguous"


def is_trend_binary(label: str) -> int:
    return 1 if label == "trend" else 0
