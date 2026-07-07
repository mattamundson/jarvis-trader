# MNQ 1h — Paper Trading Setup

## Walk-Forward Validation
- **WFE:** 0.57 (GOOD — threshold 0.50)
- **Windows:** 6/6 analyzed (2024-04-26 to 2026-03-27)
- **OOS Profitable:** 4/6 windows (67%)
- **Date approved:** 2026-03-30
- **Config file:** `engine/backtest/results/WF_MNQ_1h_adaptive_walk_forward.json`

## Filter Verdicts (FINAL — do not re-test)
| Config | WFE | Verdict |
|--------|-----|---------|
| Static params | 0.24 | OVERFIT |
| + Adaptive regime | **0.57** | GOOD — APPROVED |
| + Volume filter | -0.23 | REJECTED — HURTS |
| + MTF filter | 0.17 | REJECTED — HURTS |

**Best config: adaptive regime ONLY. Adding any filter degrades performance.**

## Signal Configuration
- **Indicator:** STC (Schaff Trend Cycle)
- **STC Oversold:** 15
- **STC Overbought:** 92
- **Stop:** 0.70 ATR
- **T1:** 1.00 ATR (50% exit)
- **T2:** 1.80 ATR (25% exit)
- **T3:** 2.618 ATR (25% exit)
- **Regime filter:** ON (required for adaptive_regime)
- **Adaptive regime:** ON — CRITICAL, lifts WFE 0.24→0.57
- **Volume filter:** OFF — NEVER ENABLE (WFE drops to -0.23)
- **MTF filter:** OFF — NEVER ENABLE (WFE drops to 0.17)

## Position Sizing
- **Risk per trade:** 0.25% of capital
- **Max daily loss:** -2%
- **Max concurrent positions:** 1
- **Contract:** MNQ (Micro Nasdaq, $2/point, 0.25 tick)

## Kill Switch
- Auto-activate if: 3 consecutive losses, OR -3% monthly
- Manual override available via `/kill-switch` endpoint

## Config Reference
```python
# engine/backtest/paper_config.py → MNQ_PAPER_CONFIG
"enabled": True
"adaptive_regime": True   # CRITICAL — lifts WFE from 0.24 to 0.57
"volume_filter": False    # NEVER ENABLE — degrades to -0.23
"mtf_filter": False       # NEVER ENABLE — degrades to 0.17
```

## Notes
- Adaptive regime is non-negotiable for MNQ — static params are OVERFIT
- MTF filter blocks good setups, not just bad ones — tested and REJECTED
- Volume filter similarly over-constrains the model — tested and REJECTED
- Extended start date (2024-04-26 vs 2024-06-01) provides more training data
