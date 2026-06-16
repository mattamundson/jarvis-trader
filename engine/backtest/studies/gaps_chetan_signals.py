"""GAPS Chetan — gap-fill variant.

The Chetan gap study (GAPS_Chetan1STUDY.ts) is a second gap-fill model. Per-bar
OHLC data does not carry its exact intraday gap classification, so this port
reuses the same fill mechanics as Gapfinder but at the larger, "measured-gap"
thresholds the Chetan variant emphasizes (bigger overnight gaps only). It is a
deliberate approximation — documented so the verdict is read with that caveat.

One entry per session; mechanics identical to gapfinder_signals (toward the
unfilled gap), only the gap-size grid differs.
"""

from __future__ import annotations

import pandas as pd

from backtest.studies.gapfinder_signals import _gap_signals

MODES = ["fill"]


def grid(mode: str) -> list[dict]:
    # Larger gaps only (Chetan "measured gap" emphasis).
    return [{"min_gap_pct": g} for g in (0.003, 0.005)]


def generate(df: pd.DataFrame, mode: str = "fill", min_gap_pct: float = 0.003) -> pd.DataFrame:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    return _gap_signals(df, min_gap_pct)
