# MES Deep Adjacent Family DM — 2026-09-12

Scope: research-only; no live engine/risk/kill-switch/broker/paper_config changes.

## Data proof
- Cache: `backtest/cache/MES_2019-05-05_2026-08-26_1h.csv`
- Bars: `43010`; span: `7.3073y`
- Command basis: `iterate.py --trades-out` + `dm_edge_screen.py --input-kind trades --trade-align index --power 1`

## Top aggregate rows
| Rank | Params | Trades | PF | Sharpe | CAGR % | p_edge | PF 95% low |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | 60/200/2.0 | 122 | 1.6952 | 0.8740 | 2.9385 | 0.9900 | 1.1135 |
| 2 | 60/200/1.8 | 122 | 1.5778 | 0.7681 | 2.7099 | 0.9825 | 1.0396 |
| 3 | 55/190/2.0 | 127 | 1.5033 | 0.6606 | 2.2859 | 0.9625 | 0.9687 |
| 4 | 55/200/2.0 | 128 | 1.3949 | 0.5608 | 1.9171 | 0.9260 | 0.8893 |
| 5 | 55/190/1.8 | 127 | 1.3848 | 0.5268 | 1.8236 | 0.9175 | 0.8719 |
| 6 | 60/190/2.0 | 122 | 1.1882 | 0.2904 | 0.9523 | 0.7700 | 0.7664 |
| 7 | 60/190/1.8 | 122 | 1.1479 | 0.2336 | 0.7822 | 0.7175 | 0.7459 |
| 8 | 55/200/1.8 | 50 | 0.9731 | -0.0286 | -0.0652 | 0.4640 | 0.4649 |

## Paired trade-level DM tests
| A | B | n | DM_HLN | p(two-sided) | Interpretation |
|---|---|---:|---:|---:|---|
| 60/200/2.0 | 60/200/1.8 | 122 | -0.5838 | 0.5604 | negative favors A directionally; not significant at 5% |
| 60/200/2.0 | 55/190/2.0 | 122 | -0.4794 | 0.6325 | negative favors A directionally; not significant at 5% |
| 60/200/1.8 | 55/190/2.0 | 122 | -0.3168 | 0.7519 | negative favors A directionally; not significant at 5% |

## Verdict
60/200/2.0 remains best aggregate, but top-row paired trade-level DM does not establish statistically significant superiority; robust family center is 55-60 fast, 190-200 slow, ATR 1.8-2.0, with 60/200/2.0 as strongest point estimate.

## Next queue
1. Promote this as a robustness-support artifact only, not a runtime/config change.
2. Optional next research: exact-date alignment DM in addition to ordinal trade-index alignment to reduce pairing artifact risk.
3. Optional next research: CPCV/DSR family-level deflation over the 8-row adjacent screen before any claims beyond “robust support”.
