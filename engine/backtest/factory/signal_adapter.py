"""Uniform signal adapter -- one calling convention for every generator.

Each StrategyCard names a signal generator as 'module.path:function'. The
generators already share a contract -- generate_*_signals(df, **params) returns a
frame carrying the Backtester's required columns -- but they differ in which
optional columns they fill. This adapter resolves the function, runs it, and
normalises the output to exactly what Backtester.run expects, so the funnel can
treat all strategies identically.
"""

from __future__ import annotations

import importlib
from typing import Callable

import pandas as pd

# Backtester.run (engine/backtest/backtester.py) requires these columns.
REQUIRED_INPUT = ["open", "high", "low", "close"]
REQUIRED_SIGNAL = ["entry_signal", "bias", "stop_level", "target_1"]
FULL_CONTRACT = [
    "open",
    "high",
    "low",
    "close",
    "entry_signal",
    "bias",
    "stop_level",
    "target_1",
    "target_2",
    "target_3",
    "regime",
    "exit_signal",
]


def resolve_signal_fn(signal_ref: str) -> Callable:
    """'backtest.meanrev_signals:generate_bollinger_rsi_signals' -> the function."""
    module_path, _, func_name = signal_ref.partition(":")
    if not module_path or not func_name:
        raise ValueError(f"bad signal_ref '{signal_ref}' (want 'module:function')")
    module = importlib.import_module(module_path)
    return getattr(module, func_name)


def build_signal_frame(
    signal_ref: str,
    bars: pd.DataFrame,
    params: dict,
) -> pd.DataFrame:
    """Run a generator and return a frame satisfying Backtester.run's contract.

    Raises if the generator fails to emit the mandatory signal columns (that means
    the generator is broken for this input, not something to paper over). Optional
    columns are backfilled with safe, non-look-ahead defaults.
    """
    for col in REQUIRED_INPUT:
        if col not in bars.columns:
            raise ValueError(f"input bars missing required column '{col}'")

    fn = resolve_signal_fn(signal_ref)
    out = fn(bars.copy(), **params)

    missing = [c for c in REQUIRED_SIGNAL if c not in out.columns]
    if missing:
        raise ValueError(f"generator '{signal_ref}' did not emit required signal columns {missing}")

    # Backfill optional columns the Backtester reads via .get() but that some
    # generators omit. target_2/3 default to target_1 (single-target exit);
    # regime/exit_signal default to inert values.
    if "target_2" not in out.columns:
        out["target_2"] = out["target_1"]
    if "target_3" not in out.columns:
        out["target_3"] = out["target_1"]
    if "regime" not in out.columns:
        out["regime"] = ""
    if "exit_signal" not in out.columns:
        out["exit_signal"] = "NO_EXIT"
    return out
