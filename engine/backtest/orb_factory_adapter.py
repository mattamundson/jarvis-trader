"""
ORB -> JARVIS Backtester signal adapter (for the discovery factory).

``orb_signals.generate_orb_signals`` emits an ``ORB_signal`` column
("LONG_ENTRY"/"SHORT_ENTRY"/"") plus ``or_high``/``or_low``/``or_range``; the
Backtester instead consumes ``entry_signal``/``bias``/``stop_level``/
``target_1``/``target_2``/``target_3`` (mirrors ``trend_signals``/
``donchian_signals``). This thin adapter bridges the two so ORB can run through
the factory's ``run_fn``/``Backtester.run`` path like any other family.

Two deliberate choices:
  * ``sub_hourly=True`` -- the opening range is the first bar at/after 09:30 ET
    (a legitimate 15-min OR on 15m bars), not every ``hour == 9`` bar.
  * Range-multiple targets -- the Backtester rejects entries with R:R < 1.2.
    ORB's native 1x-range T1 against a full-opposite-OR stop is ~1:1 and would
    be rejected, so targets are expressed as configurable multiples of the OR
    range (default T1 = 2x), which clears the gate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.orb_signals import generate_orb_signals


def generate_orb_factory_signals(
    df: pd.DataFrame,
    symbol: str = "MES",
    t1_range_mult: float = 2.0,
    t2_range_mult: float = 3.0,
    volume_filter: bool = True,
    min_or_range_pct: float = 0.0008,
) -> pd.DataFrame:
    """Opening-Range-Breakout signals in Backtester-native columns.

    Parameters mirror the grid axes used in the discovery registry. ``symbol``
    is cosmetic (ORB logging only); the factory's ``run_fn`` does not pass it,
    so it falls back to the default.
    """
    out = generate_orb_signals(
        df,
        symbol=symbol,
        volume_filter=volume_filter,
        min_or_range_pct=min_or_range_pct,
        sub_hourly=True,
    )

    sig = out["ORB_signal"].to_numpy()
    is_long = sig == "LONG_ENTRY"
    is_short = sig == "SHORT_ENTRY"

    or_high = out["or_high"].to_numpy(dtype=float)
    or_low = out["or_low"].to_numpy(dtype=float)
    or_range = out["or_range"].to_numpy(dtype=float)

    bias = np.full(len(out), "NEUTRAL", dtype=object)
    bias[is_long] = "STRONG_BULL"
    bias[is_short] = "STRONG_BEAR"

    def _target(mult: float) -> np.ndarray:
        return np.where(
            is_long,
            or_high + mult * or_range,
            np.where(is_short, or_low - mult * or_range, np.nan),
        )

    out["entry_signal"] = np.where(is_long | is_short, "ENTRY_NOW", "NO_TRADE")
    out["exit_signal"] = "NO_EXIT"  # exits handled by stop/target, no discretionary exit
    out["bias"] = bias
    # Stop = opposite side of the opening range (ORB convention).
    out["stop_level"] = np.where(is_long, or_low, np.where(is_short, or_high, np.nan))
    out["target_1"] = _target(t1_range_mult)
    out["target_2"] = _target(t2_range_mult)
    out["target_3"] = _target(t2_range_mult + 1.0)
    return out
