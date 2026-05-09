"""
Wrapper: runs MCL Hypothesis-D rank2 WFO against the latest cache file.

Monkey-patches _find_data_file in run_mcl_hypothesis_d_rank2 to always pick
the freshest cache via _find_latest_cache so this script stays valid after
each IBKR cache refresh without needing a manual path update.

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_mcl_hyp_d_rank2_fresh.py
"""

from __future__ import annotations

import sys
from pathlib import Path

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

import backtest.run_mcl_hypothesis_d_rank2 as _r2  # noqa: E402
from backtest._gate_v2_helpers import _find_latest_cache  # noqa: E402


def _find_data_file_fresh(data_dir: Path) -> Path:
    chosen = _find_latest_cache(data_dir, "MCL")
    print(f"[MCL-HD-R2-FRESH] Using latest cache: {chosen.name}")
    return chosen


_r2._find_data_file = _find_data_file_fresh

if __name__ == "__main__":
    _r2.main()
