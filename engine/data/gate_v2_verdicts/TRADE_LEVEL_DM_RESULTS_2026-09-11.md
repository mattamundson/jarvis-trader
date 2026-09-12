# Trade-Level DM Results — MES 50/55/60 × 200 × 2.0 (2026-09-11)

Scope: research-only. No live engine/risk/kill-switch/broker/paper_config changes. Results below are **preliminary** because they use the currently available local 2.37y MES 1h cache, not the missing/restorable ≥7y deep MES cache.

## Source data

- Cache: `engine/backtest/cache/MES_2024-04-26_2026-09-10_1h.csv`
- Verified span in run output: `2024-04-26 05:00:00 -> 2026-09-10 20:00:00`
- Bars: `13,734`
- Span years: `2.37`
- Sidecar producer: `engine/backtest/iterate.py --trades-out`
- DM consumer: `engine/backtest/dm_edge_screen.py --input-kind trades --trade-metric pnl --trade-align index --power 1`

## Sidecar integrity

| Combo | Aggregate trades | Sidecar rows | Actual records | PF | MC p_positive_edge |
|---|---:|---:|---:|---:|---:|
| 50/200/2.0 | 38 | 38 | 38 | 0.6297 | 0.155 |
| 55/200/2.0 | 40 | 40 | 40 | 1.4429 | 0.790 |
| 60/200/2.0 | 37 | 37 | 37 | 1.7353 | 0.930 |

All aggregate trade counts matched sidecar row counts.

## Trade-level Diebold-Mariano comparisons

Sign convention: scores are higher-is-better (`pnl`), loss is `-score`, and the loss differential is `L_A - L_B`. Therefore **negative DM favors A**; positive DM favors B.

| A | B | Align | n | DM_HLN | p(two-sided) | Interpretation |
|---|---|---|---:|---:|---:|---|
| 60/200/2.0 | 55/200/2.0 | trade index | 37 | -0.5895 | 0.5592 | A has higher mean trade PnL directionally, but not statistically distinguishable. |
| 60/200/2.0 | 50/200/2.0 | trade index | 37 | -1.6218 | 0.1136 | A directionally beats weak 50-fast neighbor, but still not significant at 5%. |

## Conclusion

The local-cache sidecars reproduce the expected aggregate ordering:

`60/200/2.0 PF 1.7353 > 55/200/2.0 PF 1.4429 > 50/200/2.0 PF 0.6297`.

However, the trade-level DM test does **not** reject equal predictive accuracy at the 5% level for either neighbor comparison on the local 2.37y cache:

- 60 vs 55: `p=0.5592`
- 60 vs 50: `p=0.1136`

This means the correct research conclusion is **directional robustness signal, not certified statistical superiority**. The toolchain is now working; the edge claim remains blocked on restoring/acquiring the ≥7y MES 1h cache and rerunning the same sidecar + DM process on deep data.

## Next recommended action

Restore/acquire a verified ≥7y MES 1h cache, regenerate 50/55/60 sidecars on that cache, then rerun trade-level DM. If the 60 vs 50 result remains directionally negative and becomes significant while 60 vs 55 stays insignificant, the interpretation would be: 50-fast is structurally weak, 55/60 are statistically similar, and the robust family center may be closer to 55–60 than a single fragile point estimate.
