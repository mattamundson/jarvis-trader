#!/usr/bin/env python
"""
JARVIS TRADER — Walk-Forward Validation CLI Runner

Executes rolling walk-forward validation to detect overfitting in the parameter
optimizer. Trains on historical windows and tests out-of-sample performance.

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_walk_forward.py --symbol MES --interval 1h
    .venv/Scripts/python backtest/run_walk_forward.py --symbol MES --interval 1h --train-months 6 --test-months 2
    .venv/Scripts/python backtest/run_walk_forward.py --symbol MCL --interval 1h --adaptive-regime --volume-filter

Core Metrics:
    - WFE (Walk-Forward Efficiency) = OOS Sharpe / IS Sharpe
      * > 0.70 = Excellent (minimal overfitting)
      * 0.50-0.70 = Good (acceptable degradation)
      * 0.30-0.50 = Marginal (significant overfitting)
      * < 0.30 = Poor (likely unusable)

    - Parameter Stability: Do optimal params vary across windows?
    - Degradation Profile: Consistent decay or erratic performance?
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure backtest module is importable
engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))


def main():
    """Entry point for walk-forward validation CLI."""
    try:
        from backtest.walk_forward import main as walk_forward_main
    except ImportError as e:
        print(f"[ERROR] Import failed: {e}")
        print("Make sure you're running from the engine/ directory.")
        sys.exit(1)

    walk_forward_main()


if __name__ == "__main__":
    main()
