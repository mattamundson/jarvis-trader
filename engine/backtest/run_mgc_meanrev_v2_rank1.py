#!/usr/bin/env python
"""
MGC Mean-Reversion v2 -- Rank 1 (vol-adaptive trigger + OU integration)

Lineage:
    MGC mean-rev rank1 (v1) FAILED gate v2:
      - p_edge=0.32, dsr=0, pf_ci_lower=0.72, wfo_consistency=WEAK
      - 325 OOS trades (NOT a sparsity problem)
      - best combo PF=1.17, worst 0.33, mean 0.83 — losses systemic across grid

    Diagnosis (meanrev_audit.md): three structural failures, not gate strictness.

v2 attempt 1 — MGC is the cleanest test case for OU integration because:
  - Gold cycles around macro events at well-defined frequencies
  - Existing `engine/strategies/mean_reversion_ou.py` is unused
  - MGC's narrower distribution kurtosis (vs MCL) should be more OU-like

Grid (v2 rank1 MGC): 8 combos focused on OU mode + dislocation
    ou_mode                  : ["filter", "zscore_trigger"]
    ou_min_half_life_bars    : [4, 8]
    dislocation_percentile_min: [90, 95]

All other params at MEANREV_V2_DEFAULTS.

If "filter" mode passes, v1's Bollinger+RSI is still the trigger but the
OU half-life requirement screens out random-walk regimes.

If "zscore_trigger" mode passes, the entire entry condition is replaced by
OU z-score crossings — this is the "pure OU" cyclical strategy.

Gate v2 ALT path threshold (same as v1):
    dsr                  >= 0.30
    wfo_consistency      in {MODERATE, STRONG}
    fixed_params_min_pf  >= 1.20
    cost_survives_through >= "realistic"
    mc_95th_dd_pct       <= 7.0

Contract specs (identical to v1):
    Multiplier : $10/point   (Micro Gold)
    Commission : $0.62/contract round-trip
    Slippage   : 2 ticks
    Capital    : $50,000

Writes: engine/data/gate_v2_verdicts/MGC_meanrev_v2_rank1.json
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from backtest import meanrev_v2_signals  # noqa: E402
from backtest.contract_specs import CONTRACT_SPECS  # noqa: E402

SYMBOL = "MGC"
MULTIPLIER = 10.0
CAPITAL = 50_000.0
TICK_SIZE = 0.10
# Imported from contract_specs.py (single source of truth) rather than a
# local literal -- this file previously hardcoded 0.62, MES's rate, instead
# of MGC's documented 0.85 (found 2026-07-10). contract_specs.py's own
# docstring exists precisely because this class of drift ("MCL commission
# was 0.62 in one script and 0.85 in another") has happened before.
COMMISSION = CONTRACT_SPECS["MGC"].commission
SLIPPAGE_TICKS = 2.0

TRAIN_MONTHS = 6
TEST_MONTHS = 2
STEP_MONTHS = 1
N_WINDOWS = 18

# Grid: 2 × 2 × 2 = 8 combos
OU_MODE_VALUES = ["filter", "zscore_trigger"]
OU_MIN_HALF_LIFE_VALUES = [4, 8]
DISLOCATION_PCT_MIN_VALUES = [90.0, 95.0]

COST_SWEEP_TIERS = {
    "optimistic": {"commission": round(COMMISSION * 0.5, 4), "slippage_ticks": 1.0},
    "realistic": {"commission": round(COMMISSION * 1.0, 4), "slippage_ticks": 2.0},
    "pessimistic": {"commission": round(COMMISSION * 2.0, 4), "slippage_ticks": 3.0},
    "catastrophic": {"commission": round(COMMISSION * 4.0, 4), "slippage_ticks": 4.0},
}

VERDICT_FILE = (
    Path(__file__).parent.parent / "data" / "gate_v2_verdicts" / "MGC_meanrev_v2_rank1.json"
)


def make_v2_signal_fn(ou_mode: str, ou_min_hl: int, dpm: float):
    def signal_fn(df):
        return meanrev_v2_signals.generate_meanrev_v2_signals(
            df,
            ou_mode=ou_mode,
            ou_min_half_life_bars=ou_min_hl,
            dislocation_percentile_min=dpm,
            capital_for_cb=CAPITAL,
        )

    return signal_fn


def main():
    print(
        "[MGC-MR-V2-1] Runner shell — integrate make_v2_signal_fn() into the WFO "
        "loop from run_mgc_meanrev_rank1.py (or wfo_primitives.run_wfo())."
    )
    print(f"[MGC-MR-V2-1] Will write verdict to: {VERDICT_FILE}")
    grid = list(
        itertools.product(OU_MODE_VALUES, OU_MIN_HALF_LIFE_VALUES, DISLOCATION_PCT_MIN_VALUES)
    )
    print(f"[MGC-MR-V2-1] Grid size: {len(grid)} combos")
    for i, (om, ohl, dpm) in enumerate(grid):
        print(f"  [{i+1:02d}] ou_mode={om}, ou_min_hl={ohl}, dislocation_pct_min={dpm}")


if __name__ == "__main__":
    main()
