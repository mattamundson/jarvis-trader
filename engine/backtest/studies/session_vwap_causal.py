"""Research-only causal RTH session VWAP reference.

Unlike the legacy VWAP signal generator, this implementation explicitly gates
both accumulation and eligibility to the configured RTH session and resets once
per session at the first eligible bar. It is bar-frequency agnostic.
"""

from __future__ import annotations

from datetime import time

import numpy as np
import pandas as pd


def compute_session_vwap_causal(
    df: pd.DataFrame,
    *,
    session_tz: str = "America/New_York",
    naive_tz: str = "UTC",
    rth_open: time = time(9, 30),
    rth_close: time = time(16, 0),
    entry_cutoff: time = time(15, 0),
) -> pd.DataFrame:
    """Compute point-in-time RTH VWAP with explicit session/entry gates.

    Required columns: high, low, close, volume.
    Timezone-naive input is interpreted using ``naive_tz`` (UTC matches the
    repository's IBKR/Yahoo cache convention) then converted to ``session_tz``.

    VWAP is NaN outside RTH. Zero-volume RTH bars do not change the cumulative
    numerator/denominator; before any positive-volume bar, typical price is used
    as the same fallback shown in the TOS reference.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame must have a DatetimeIndex")
    required = {"high", "low", "close", "volume"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    if rth_open >= rth_close:
        raise ValueError("rth_open must be before rth_close")
    if not (rth_open <= entry_cutoff <= rth_close):
        raise ValueError("entry_cutoff must fall within RTH")

    result = df.copy()
    local_index = result.index
    if local_index.tz is None:
        local_index = local_index.tz_localize(naive_tz)
    local_index = local_index.tz_convert(session_tz)

    result["session_vwap"] = np.nan
    result["rth_eligible"] = False
    result["entry_eligible"] = False
    result["session_cum_volume"] = np.nan

    local_dates = pd.Index(local_index.date)
    local_times = pd.Index(local_index.time)

    for session_date in pd.unique(local_dates):
        positions = np.flatnonzero(local_dates == session_date)
        cumulative_pv = 0.0
        cumulative_volume = 0.0

        for position in positions:
            bar_time = local_times[position]
            in_rth = rth_open <= bar_time < rth_close
            if not in_rth:
                continue

            result.iloc[position, result.columns.get_loc("rth_eligible")] = True
            result.iloc[position, result.columns.get_loc("entry_eligible")] = (
                bar_time < entry_cutoff
            )

            high = float(result.iloc[position]["high"])
            low = float(result.iloc[position]["low"])
            close = float(result.iloc[position]["close"])
            volume = float(result.iloc[position]["volume"])
            typical_price = (high + low + close) / 3.0

            if volume > 0:
                cumulative_pv += typical_price * volume
                cumulative_volume += volume

            vwap = cumulative_pv / cumulative_volume if cumulative_volume > 0 else typical_price
            result.iloc[position, result.columns.get_loc("session_vwap")] = vwap
            result.iloc[position, result.columns.get_loc("session_cum_volume")] = cumulative_volume

    return result
