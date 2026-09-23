# Deep-Cache Trade-Level DM Results — MES 50/55/60 × 200 × 2.0 (2026-09-11)

Scope: research-only. No live engine/risk/kill-switch/broker/`paper_config.py` changes. This artifact uses the restored ≥7y MES 1h cache and supersedes the earlier local 2.37y-only preliminary report for the specific 50/55/60 × 200 × 2.0 neighborhood.

## Source data

- Restored cache source: `C:/Users/mattm/Archive/2026/ci-cache-cleanup/MES_2019-05-05_2026-08-26_1h.csv`
- Active worktree cache copy: `engine/backtest/cache/MES_2019-05-05_2026-08-26_1h.csv`
- Rows: `43,010`
- Verified span: `2019-05-05 22:00:00+00:00` → `2026-08-26 20:00:00+00:00`
- Span years reported by iterator: `7.31y`
- Duplicate timestamps: `0`
- OHLC violations: `0`
- NaN OHLC rows: `0`
- Large gaps >96h in rough scan: `0`
- Sidecar producer: `engine/backtest/iterate.py --trades-out`
- DM consumer: `engine/backtest/dm_edge_screen.py --input-kind trades --trade-metric pnl --trade-align index --power 1`

## Sidecar integrity

| Combo | Aggregate trades | Sidecar rows | Match | Profit factor | Sharpe | CAGR | Max DD | MC p_positive_edge | MC median PF | MC PF 95% low |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 50/200/2.0 | 81 | 81 | yes | 0.9613 | -0.0535 | -0.1363% | 0.0520 | 0.4435 | 0.9647 | 0.5512 |
| 55/200/2.0 | 128 | 128 | yes | 1.3949 | 0.5608 | 1.9171% | 0.0448 | 0.9260 | 1.3810 | 0.8893 |
| 60/200/2.0 | 122 | 122 | yes | 1.6952 | 0.8740 | 2.9385% | 0.0448 | 0.9900 | 1.6909 | 1.1135 |

## Trade-level Diebold-Mariano comparisons

Sign convention: scores are higher-is-better (`pnl`), loss is `-score`, and the loss differential is `L_A - L_B`. Therefore **negative DM favors A**; positive DM favors B.

| A | B | Align | n | Dropped A tail | Dropped B tail | DM_HLN | p(two-sided) | Interpretation |
|---|---|---|---:|---:|---:|---:|---:|---|
| 60/200/2.0 | 55/200/2.0 | trade index | 122 | 0 | 6 | -0.8385 | 0.4034 | 60 has higher mean trade-PnL directionally, but not statistically distinguishable from 55. |
| 60/200/2.0 | 50/200/2.0 | trade index | 81 | 41 | 0 | -1.2079 | 0.2307 | 60 directionally beats 50, but not significant at 5% on paired ordinal trades. |

## Certification verdict

Deep-cache aggregate ordering is robust and economically cleaner than the local-cache result:

`60/200/2.0 PF 1.6952 > 55/200/2.0 PF 1.3949 > 50/200/2.0 PF 0.9613`.

However, the paired trade-level DM tests still do **not** reject equal predictive accuracy at the 5% level:

- 60 vs 55: `p=0.4034`
- 60 vs 50: `p=0.2307`

Correct conclusion:

1. `60/200/2.0` remains the strongest member of this tested neighborhood by PF, Sharpe, CAGR, and MC p_positive_edge.
2. `55/200/2.0` is a credible adjacent parameter with positive aggregate performance, which reduces the single-point fragility concern.
3. `50/200/2.0` is weak/near-flat on deep data and should not be treated as equivalent by aggregate metrics, even though ordinal trade-level DM does not hit 5% significance.
4. The family shows directional robustness around 55–60 fast MA, but the DM result does **not** justify claiming statistically certified superiority of 60 over nearby alternatives.

## Next recommended action

Promote this result as a **robustness support artifact**, not a live/risk config change. The next research step is to run the same deep-cache sidecar + DM process for adjacent slow/ATR variations around the 55–60/200/2.0 family center before considering any value-area overlay.
