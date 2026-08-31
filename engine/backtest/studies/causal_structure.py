"""Causal research ports of selected Corey market-structure studies.

Only source equations that can be known at or before the current completed bar
are preserved here.  Future-aware chart arrows are intentionally excluded.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def rangefinder_expansion_core(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
) -> pd.DataFrame:
    """Causal core of Corey Rangefinder expansion geometry.

    The source's ``exHigh``/``exLow`` condition reduces to an outside bar:
    current high > prior high AND current low < prior low.  This function emits
    that event at the current bar close and reproduces only contemporaneously
    knowable range/extension geometry.  The legacy arrow rules using ``[-1]``
    and ``[-2]`` references are deliberately not ported.
    """
    outside = (high > high.shift(1)) & (low < low.shift(1))
    direction = pd.Series(np.where(close >= open_, 1.0, -1.0), index=close.index)
    bar_range = high - low
    imbalance = pd.Series(np.where(close >= open_, high, low), index=close.index)

    frame = pd.DataFrame(index=close.index)
    frame["range_expansion"] = outside.fillna(False)
    frame["range_high"] = high.where(outside)
    frame["range_low"] = low.where(outside)
    frame["range_mid"] = ((high + low) / 2.0).where(outside)
    frame["range_size"] = bar_range.where(outside)
    frame["direction"] = direction.where(outside)
    frame["entry_reference"] = close.where(outside)
    frame["extension_0_382"] = (imbalance + direction * bar_range * 0.382).where(outside)
    frame["extension_0_500"] = (imbalance + direction * bar_range * 0.500).where(outside)
    frame["extension_0_618"] = (imbalance + direction * bar_range * 0.618).where(outside)
    frame["extension_0_786"] = (imbalance + direction * bar_range * 0.786).where(outside)
    frame["extension_1_000"] = (imbalance + direction * bar_range).where(outside)
    frame["extension_2_000"] = (imbalance + direction * bar_range * 2.0).where(outside)
    return frame


def singlefinder_confirmed(
    high: pd.Series,
    low: pd.Series,
) -> pd.DataFrame:
    """Delayed-confirmation causal form of Corey Singlefinder v2.

    The source paints a single on bar ``t`` using data from ``t+1``.  A live
    system therefore cannot know the structure on ``t``.  This function emits
    the feature on confirmation bar ``j=t+1`` instead:

    bearish: high[j] < low[j-2] and high[j-1] > low[j-2]
    bullish: high[j-2] < low[j] and high[j-1] > low[j]

    Zone boundaries preserve the source plots but become available only on the
    confirmation bar.  No value is backfilled to the historical candidate bar.
    """
    bearish = (high < low.shift(2)) & (high.shift(1) > low.shift(2))
    bullish = (high.shift(2) < low) & (high.shift(1) > low)

    frame = pd.DataFrame(index=high.index)
    frame["bearish_single_confirmed"] = bearish.fillna(False)
    frame["bearish_zone_low"] = high.where(bearish)
    frame["bearish_zone_high"] = low.shift(2).where(bearish)
    frame["bullish_single_confirmed"] = bullish.fillna(False)
    frame["bullish_zone_low"] = high.shift(2).where(bullish)
    frame["bullish_zone_high"] = low.where(bullish)
    frame["confirmation_delay_bars"] = pd.Series(
        np.where(bearish | bullish, 1.0, np.nan), index=high.index
    )
    return frame
