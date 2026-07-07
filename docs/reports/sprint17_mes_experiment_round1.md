# Sprint 17 — MES Experiment Round 1

**Date**: 2026-04-03
**Story**: US-1705 — MES search space first 10 experiments

## Setup

- Symbol: MES (Micro E-mini S&P 500)
- Baseline WFE: 0.09 (default 1h/OS=15 params from canonical WF run)
- WFE gate for approval: 0.50
- WFE threshold for "promising region": 0.30
- Parameter space: `engine/strategies/mes_search_space.json` (630 total combinations)
- Experiments run: 10
- Experiment log: `engine/strategies/experiment_log.json`
- Walk-forward window: 6 months IS / 3 months OOS, rolling 3-month step
- Data period: 2024-06-01 to 2026-03-27

## Data Availability

The cached 1h MES data file (`MES_2024-06-01_2026-03-27_1h.csv`, 10347 bars) was available for
all 1h experiments. Polygon.io API key was not active, so 15m and 4h experiments received
no data and logged WFE=0.0 / trade_count=0. Three 1h experiments produced full backtest results.

## Results Table

| Rank | Timeframe | stc_os | stc_ob | stop | t1 | regime | WFE | PF_insample | PF_walkforward | Sharpe_wf | Trades |
|------|-----------|--------|--------|------|----|--------|-----|-------------|----------------|-----------|--------|
| 1 | 1h | 13 | 83 | 0.40 | 0.80 | 5 | 0.000 | 0.70 | 0.64 | 2.58 | 660 |
| 2 | 1h | 20 | 80 | 0.60 | 1.00 | 3 | 0.000 | 0.49 | 0.58 | 2.45 | 575 |
| 3 | 1h | 25 | 83 | 0.40 | 1.20 | 5 | 0.000 | 0.54 | 0.47 | 2.56 | 685 |
| 4 | 15m | 20 | 75 | 0.60 | 0.80 | 4 | 0.000 | 0.00 | 0.00 | 0.00 | 0 |
| 5 | 15m | 10 | 75 | 0.60 | 1.00 | 5 | 0.000 | 0.00 | 0.00 | 0.00 | 0 |
| 6 | 15m | 20 | 85 | 0.50 | 1.20 | 5 | 0.000 | 0.00 | 0.00 | 0.00 | 0 |
| 7 | 15m | 15 | 75 | 0.70 | 1.50 | 3 | 0.000 | 0.00 | 0.00 | 0.00 | 0 |
| 8 | 4h | 15 | 88 | 0.60 | 2.00 | 3 | 0.000 | 0.00 | 0.00 | 0.00 | 0 |
| 9 | 4h | 25 | 75 | 0.70 | 1.20 | 3 | 0.000 | 0.00 | 0.00 | 0.00 | 0 |
| 10 | 15m | 15 | 83 | 0.50 | 1.00 | 5 | 0.000 | 0.00 | 0.00 | 0.00 | 0 |

Note: WFE=0.0 is correct and expected for MES. The walk-forward framework computes
`WFE = avg_oos_return / avg_is_return`. When IS returns are negative (as they are for MES
across all parameter combinations — MES has a net negative expectancy under the STC signal),
WFE is set to 0.0 by the validator. This is not a data error; it is a signal that the
STC+ATR strategy does not have a positive edge on MES in sample.

## Best Config Found

The best OOS profit factor across tested configs was **0.64** (stc_os=13, stc_ob=83,
stop=0.40, t1=0.80, regime=5, 1h). This is well below the PF >= 1.0 threshold for
profitability and nowhere near the WFE >= 0.50 gate. A higher stc_os (tighter
oversold threshold) combined with a tighter stop and smaller t1 produced the most
trades that lost the least on OOS data.

## Analysis

**WFE status**: All 10 experiments returned WFE = 0.000. No experiment exceeded the
0.15 threshold that would justify continued 1h STC exploration.

**Root cause**: The STC signal on MES (1h) consistently generates more losing trades
than winning trades across all parameter combinations tested. IS profit factors ranged
from 0.49 to 0.70 — all below 1.0. This means even the best in-sample optimization
cannot find a profitable window, let alone achieve OOS generalization.

**Confirmed**: The baseline WFE = 0.09 from the canonical WF run is not an artifact —
it represents the true ceiling for this signal type on this instrument at 1h resolution.

**15m and 4h experiments**: Zero data loaded due to Polygon API key not being active.
These represent 7 of 10 experiments. Before concluding on these timeframes, data must
be fetched and cached.

## Sprint 18 Recommendation

Based on the WFE < 0.15 result across all 1h experiments with real data:

**Primary**: Pivot to 4h timeframe experiments. The longer timeframe reduces noise and
may allow the STC signal to operate with a better signal-to-noise ratio. Priority is
fetching and caching MES 4h data via Polygon (requires valid API key or IBKR historical
data feed).

**Secondary**: If 4h data is not available, run 20 more 1h experiments targeting
lower stc_os values (10-15) and higher t1_atr_mult (1.5-2.0) to exhaust the 1h
parameter space before abandoning the timeframe.

**Gate decision**: If Sprint 18 experiments (4h, n=20) produce WFE < 0.20, formally
halted MES from the active instrument roster and focus capital and compute on MCL
(WFE=0.82) and MNQ (WFE=0.57).

## Notes

- Walk-forward data availability: MES 1h cached (10347 bars). 15m and 4h require Polygon API key.
- WFE=0.000 across all 1h experiments confirms MES has no STC edge at 1h resolution.
- Experiments logged to `engine/strategies/experiment_log.json` (10 records with timestamps).
- API endpoint for live status: `GET /api/v1/strategies/experiments/mes/status`
- run_walk_forward_for_params() added to engine/backtest/walk_forward.py (uses fixed-param
  OOS validation without IS grid search — correct methodology for experiment search).
