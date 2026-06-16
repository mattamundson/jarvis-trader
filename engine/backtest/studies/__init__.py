"""ThinkScript strategy sweep — pluggable study modules.

Each ``<name>_signals`` module in this package implements one Corey/Saty study
as a mechanical, backtestable strategy exposing the standard interface consumed
by ``backtest.study_wfo_runner``:

    MODES: list[str]
        The mechanical modes the study supports (e.g. ["go", "fade"],
        ["trend", "reversion"], ["fill"]).

    def grid(mode: str) -> list[dict]:
        A SMALL pre-registered parameter grid (<=4 combos) for the mode. Keeping
        it small keeps the deflated-Sharpe n_trials honest.

    def generate(df: pd.DataFrame, mode: str, **params) -> pd.DataFrame:
        Return a frame carrying the Backtester contract columns
        (entry_signal, bias, stop_level, target_1/2/3, atr, regime,
        exit_signal). RTH-only, no look-ahead, one entry per session.

The runner discovers a study by importing ``backtest.studies.<name>_signals`` —
no central registry to edit, so study modules stay file-isolated.
"""

from __future__ import annotations

import importlib
from types import ModuleType

#: Studies known to the sweep. Each maps to a module ``<value>`` in this package.
#: Extended as batches land; the runner can also load any module by name.
KNOWN_STUDIES: dict[str, str] = {
    "saty": "saty_atr_signals",
    "tscore": "tscore_signals",
    "gapfinder": "gapfinder_signals",
    "singlefinder": "singlefinder_signals",
    "rangefinder": "rangefinder_signals",
    "gaps_chetan": "gaps_chetan_signals",
    "stc": "stc_signals",
    "kama": "kama_signals",
    "cohen": "cohen_composite_signals",
}


def load_study(name: str) -> ModuleType:
    """Import and return a study module by short name or module name."""
    mod_name = KNOWN_STUDIES.get(name, name)
    if not mod_name.endswith("_signals"):
        mod_name = f"{mod_name}_signals"
    return importlib.import_module(f"backtest.studies.{mod_name}")
