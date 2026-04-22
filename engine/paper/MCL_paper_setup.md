# MCL 1h — Paper Trading Setup

## Walk-Forward Validation
- **WFE:** 0.82 (EXCELLENT — threshold 0.50)
- **Windows:** 6/6 analyzed (2024-06-01 to 2026-03-27)
- **OOS Profitable:** 5/6 windows (83%)
- **Date approved:** 2026-03-30
- **Config file:** `engine/backtest/results/WF_MCL_1h_walk_forward.json`

## Signal Configuration
- **Indicator:** STC (Schaff Trend Cycle)
- **STC Oversold:** 15
- **STC Overbought:** 83
- **Stop:** 0.90 ATR
- **T1:** 1.50 ATR (50% exit)
- **T2:** 2.618 ATR (25% exit)
- **T3:** 4.00 ATR (25% exit)
- **Regime filter:** ON
- **Adaptive regime:** OFF — adaptive WFE=-0.31, WORSE than static 0.82
- **Volume filter:** OFF (not tested for MCL)
- **MTF filter:** OFF (not tested for MCL)

## Position Sizing
- **Risk per trade:** 0.25% of capital
- **Max daily loss:** -2%
- **Max concurrent positions:** 1
- **Contract:** MCL (Micro Crude Oil, 1000 barrels, $100/point)

## Kill Switch
- Auto-activate if: 3 consecutive losses, OR -3% monthly
- Manual override available via `/kill-switch` endpoint

## Config Reference
```python
# engine/backtest/paper_config.py → MCL_PAPER_CONFIG
"enabled": True
"adaptive_regime": False  # CRITICAL — static beats adaptive for MCL
"regime_filter": True
```

## Notes
- Static params outperform adaptive for MCL (adaptive WFE=-0.31 vs static 0.82)
- Oil is regime-sensitive; regime filter appropriate
- Do NOT add volume or MTF filters — not tested, risk of degradation
- Highest WFE of all tested instruments
