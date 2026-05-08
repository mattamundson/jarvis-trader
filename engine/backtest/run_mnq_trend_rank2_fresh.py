"""
Wrapper: runs MNQ trend rank2 WFO against the fresh merged cache file
(2024-04-01 to 2026-05-07) instead of the default primary ending 2026-03-27.

This script monkey-patches _find_data_file before importing run_mnq_trend_rank2
so no existing files are modified.
"""
from __future__ import annotations

import sys
from pathlib import Path

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

import backtest.run_mnq_trend_rank2 as _r2  # noqa: E402

# Override _find_data_file to point at the fresh merged file
FRESH_FILE = engine_root / "backtest" / "cache" / "MNQ_2024-04-01_2026-05-07_1h.csv"

def _find_data_file_fresh(data_dir: Path) -> Path:
    if FRESH_FILE.exists():
        print(f"[MNQ-R2-FRESH] Using fresh merged file: {FRESH_FILE.name}")
        return FRESH_FILE
    raise FileNotFoundError(f"Fresh merged file not found: {FRESH_FILE}")

_r2._find_data_file = _find_data_file_fresh

if __name__ == "__main__":
    _r2.main()
