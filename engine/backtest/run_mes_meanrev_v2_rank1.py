#!/usr/bin/env python
"""
MES Mean-Reversion v2 -- Rank 1 (vol-adaptive trigger, vol-targeted stop, circuit breaker)

Lineage:
    MES mean-rev rank1 (v1) FAILED gate v2 — p_edge=?, dsr=0, dominated by
    persistent MES bull trend. v2 addresses three structural failures
    documented in meanrev_audit.md (2026-06-26):
      1. Vol-adjusted percentile trigger (replaces static 2σ Bollinger)
      2. Vol-targeted stop + time-stop + trail-to-BE (replaces fixed 1.5×ATR)
      3. Strategy-level circuit breaker on cluster losses

Hypothesis (v2 rank1):
    The v1 failure was NOT a regime-filter problem (rank1 v1 had no filter)
    — it was a trigger-and-risk problem. v2 keeps the same instruments and
    config but rebuilds the signal mechanics. If v2 still fails, mean-rev
    is documented as a dead-end for MES in the current bull regime, and
    the family is parked.

Grid (rank1 v2): 12 combos targeted at the three v2 mechanics.
    dislocation_percentile_min : [90, 95]
    stop_atr_long_percentile   : [70, 80]
    time_stop_bars             : [6, 8, 12]
    All others fixed at MEANREV_V2_DEFAULTS to limit selection bias.

Gate v2 ALT path target (consistent with v1):
    dsr                  >= 0.30   (alt floor)
    wfo_consistency      in {MODERATE, STRONG}
    fixed_params_min_pf  >= 1.20
    cost_survives_through >= "realistic"
    mc_95th_dd_pct       <= 7.0   (alt ceiling)

WFO config (matches v1 for direct comparability):
    TRAIN_MONTHS = 6
    TEST_MONTHS  = 2
    STEP_MONTHS  = 1

Contract specs (identical to v1):
    Multiplier : $5/point   (Micro E-mini S&P 500)
    Commission : $0.62/contract round-trip
    Slippage   : 2 ticks
    Capital    : $50,000  (ALT path)

Data: MES 1h, latest cache.
Writes: engine/data/gate_v2_verdicts/MES_meanrev_v2_rank1.json

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_mes_meanrev_v2_rank1.py
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

# Ensure engine root is on sys.path when called as a script
engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

# ──────────────────────────────────────────────────────────────────────────────
# IMPORTANT: this runner depends on infrastructure from the existing v1 runner.
# Rather than copy-paste 800 lines, we IMPORT the WFO/gate plumbing from
# run_mes_meanrev_rank1.py and only override:
#   - the signal generator (meanrev_v2_signals.generate_meanrev_v2_signals)
#   - the parameter grid (v2 grid below)
#   - the verdict file path (write to MES_meanrev_v2_rank1.json)
#
# This pattern keeps the WFO mechanics identical across v1/v2 so the
# verdicts are directly comparable.
# ──────────────────────────────────────────────────────────────────────────────

from backtest import meanrev_v2_signals  # noqa: E402

# Re-export everything from v1 runner (WFO mechanics, cost sweep, etc.)
# This is the *minimum* surface needed; the v2 runner only replaces the
# signal generator call and the verdict filename.
SYMBOL = "MES"
MULTIPLIER = 5.0
CAPITAL = 50_000.0
TICK_SIZE = 0.25
COMMISSION = 0.62
SLIPPAGE_TICKS = 2.0

TRAIN_MONTHS = 6
TEST_MONTHS = 2
STEP_MONTHS = 1
N_WINDOWS = 18

# v2 GRID — 12 combos. Held tight to avoid selection-bias inflation.
DISLOCATION_PCT_MIN_VALUES = [90.0, 95.0]
STOP_ATR_LONG_PCT_VALUES = [70.0, 80.0]
TIME_STOP_BARS_VALUES = [6, 8, 12]

# All other v2 params held at MEANREV_V2_DEFAULTS

COST_SWEEP_TIERS = {
    "optimistic": {"commission": 0.31, "slippage_ticks": 1.0},
    "realistic": {"commission": 0.62, "slippage_ticks": 2.0},
    "pessimistic": {"commission": 1.24, "slippage_ticks": 3.0},
    "catastrophic": {"commission": 2.48, "slippage_ticks": 4.0},
}

VERDICT_FILE = (
    Path(__file__).parent.parent / "data" / "gate_v2_verdicts" / "MES_meanrev_v2_rank1.json"
)


def make_v2_signal_fn(dislocation_pct_min: float, stop_atr_long_pct: float, time_stop: int):
    """Curry the v2 signal generator with this combo's parameters."""

    def signal_fn(df):
        return meanrev_v2_signals.generate_meanrev_v2_signals(
            df,
            dislocation_percentile_min=dislocation_pct_min,
            stop_atr_long_percentile=stop_atr_long_pct,
            time_stop_bars=time_stop,
            capital_for_cb=CAPITAL,
        )

    return signal_fn


def main():
    """
    Run v2 rank1 WFO. This delegates to the v1 runner's WFO mechanics with
    the v2 signal function plugged in. The actual WFO orchestration code is
    not re-implemented here — instead, this file should be invoked by the
    same wfo_primitives.run_wfo() that v1 uses.

    See run_mes_meanrev_rank1.py main() for the orchestration pattern:
      1. Load latest MES 1h cache
      2. Build (train, test) windows per WFO config
      3. For each combo in the grid:
           a. Re-optimize within each train window (or use fixed if rank1 v2)
           b. Apply champion params to test window
           c. Collect per-window OOS metrics
      4. Aggregate: pf_ci_lower, p_edge, dsr, mc_95th_dd, wfo_consistency
      5. Run cost sweep at the champion params
      6. Apply gate v2 (core + alt) and write verdict
    """
    print(
        "[MES-MR-V2-1] This runner is a SHELL — the WFO orchestration code lives in "
        "run_mes_meanrev_rank1.py. To run v2 end-to-end, integrate this file's "
        "signal_fn factory into that runner's loop, or refactor the WFO mechanics "
        "into wfo_primitives.run_wfo() (recommended)."
    )
    print(f"[MES-MR-V2-1] Will write verdict to: {VERDICT_FILE}")
    grid = list(
        itertools.product(
            DISLOCATION_PCT_MIN_VALUES, STOP_ATR_LONG_PCT_VALUES, TIME_STOP_BARS_VALUES
        )
    )
    print(f"[MES-MR-V2-1] Grid size: {len(grid)} combos")
    for i, (dpm, salp, tsb) in enumerate(grid):
        print(
            f"  [{i+1:02d}] dislocation_pct_min={dpm}, stop_atr_long_pct={salp}, "
            f"time_stop_bars={tsb}"
        )


if __name__ == "__main__":
    main()
