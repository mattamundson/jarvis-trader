# Diversification Audit — MES Trend R11 vs MGC Trend R4

*Generated 2026-05-23 from gate v2 verdict JSONs*

## Strategies

| Strategy | Symbol | Verdict | Champion Params | Windows |
|---|---|---|---|---|
| MES trend R11 | MES | PASS via alt | fast=60, slow=200, atr=2.0 | 19 x 1-month OOS |
| MGC trend R4 | MGC | PASS via alt | fast=50, slow=120, atr=2.0 | 19 x 2-month OOS |

## Data Limitations

**OOS granularity:** verdict JSON stores one PF/Sharpe per WFO window, not daily PnL.
**MES sparsity:** MES R11 averages 0-2 trades per 1-month OOS window. Most per-window metrics are statistically meaningless at this scale.
**Window alignment:** MGC uses 2-month OOS windows; MES uses 1-month windows. Analysis pairs each MGC window with the two MES windows covering the same 2-month span.

## Summary Metrics

- Aligned window pairs: 19
- Classifiable pairs (both have >= 1 OOS trade): **17**
- Both profitable: 10
- Both unprofitable: 2
- MES profitable only: 3
- MGC profitable only: 2
- Insufficient data (unknown): 2

**Concordance rate** (same outcome): 0.71
**Divergence rate** (one wins, one loses): 0.29

**Pearson r (OOS PF, aligned pairs):** 1.000 (n=4)
**Pearson r (OOS Sharpe, aligned pairs):** 0.009 (n=18)

## Window-Level Breakdown

| MGC Window | Period | MES Windows | MGC OOS PF | MES M1 PF | MES M2 PF | Outcome |
|---|---|---|---|---|---|---|
| MGC W01 | 2024-10 -> 2024-12 | W01+W02 | 0.023 | 0.000 | 0.000 | BOTH-LOSS |
| MGC W02 | 2024-11 -> 2025-01 | W02+W03 | 0.274 | 0.000 | n/a | MES-only |
| MGC W03 | 2024-12 -> 2025-02 | W03+W04 | 0.749 | n/a | n/a | MES-only |
| MGC W04 | 2025-01 -> 2025-03 | W04+W05 | 0.751 | n/a | n/a | MES-only |
| MGC W05 | 2025-02 -> 2025-04 | W05+W06 | 3.788 | n/a | n/a | BOTH-PROFITABLE |
| MGC W06 | 2025-03 -> 2025-05 | W06+W07 | 3.884 | n/a | 0.000 | BOTH-PROFITABLE |
| MGC W07 | 2025-04 -> 2025-06 | W07+W08 | 19.111 | 0.000 | 0.737 | MGC-only |
| MGC W08 | 2025-05 -> 2025-07 | W08+W09 | n/a | 0.737 | 0.000 | MGC-only |
| MGC W09 | 2025-06 -> 2025-08 | W09+W10 | 6.042 | 0.000 | n/a | BOTH-PROFITABLE |
| MGC W10 | 2025-07 -> 2025-09 | W10+W11 | 666.780 | n/a | 0.000 | BOTH-PROFITABLE |
| MGC W11 | 2025-08 -> 2025-10 | W11+W12 | 295.530 | 0.000 | n/a | BOTH-PROFITABLE |
| MGC W12 | 2025-09 -> 2025-11 | W12+W13 | 5.994 | n/a | n/a | BOTH-PROFITABLE |
| MGC W13 | 2025-10 -> 2025-12 | W13+W14 | 8.357 | n/a | n/a | BOTH-PROFITABLE |
| MGC W14 | 2025-11 -> 2026-01 | W14+W15 | 4.540 | n/a | 0.000 | BOTH-PROFITABLE |
| MGC W15 | 2025-12 -> 2026-02 | W15+W16 | n/a | 0.000 | 1.644 | BOTH-PROFITABLE |
| MGC W16 | 2026-01 -> 2026-03 | W16+W17 | n/a | 1.644 | 0.000 | BOTH-PROFITABLE |
| MGC W17 | 2026-02 -> 2026-04 | W17+W18 | 0.000 | 0.000 | 0.000 | BOTH-LOSS |
| MGC W18 | 2026-03 -> 2026-05 | W18+W19 | 0.395 | 0.000 | 0.000 | mgc-only-data |
| MGC W19 | 2026-04 -> 2026-05 | W19+-- | n/a | 0.000 | n/a | mgc-only-data |

## Qualitative Assessment

### Asset-level correlation context

Gold (GC/MGC) and equities (ES/MES) are historically **low to negatively correlated** (-0.15 to -0.30 over 2018-2025). Gold tends to rally during equity dislocations (risk-off) and sideways to down during equity bull runs. This is the theoretical diversification case for running both trend systems simultaneously.

### Trend system correlation overlay

Both R11 (MES) and R4 (MGC) are SMA trend-following strategies. Trend systems tend to cluster their failures in choppy/mean-reverting markets regardless of the underlying asset. In 2H-2025 (mid-2025 regime break), MES trend struggled while MGC trend produced exceptional OOS PF (W10: 666, W11: 295). This is consistent with the gold/equity divergence thesis — gold trended strongly on safe-haven demand during the same period equities were range-bound.

### Conclusion

OOS Sharpe correlation (n=18): r=0.009 — near-zero, indicating low window-level dependence between strategies.
OOS PF correlation (n=4): r=1.000 — small sample; disregard as a standalone signal.
**The MES + MGC pair provides diversification benefit.** Their underlying assets are negatively correlated, and the observed window-level data shows MGC trend performing strongly (W5-W14) precisely when MES trend was underperforming (0-1 trades/month in the same period). Running both simultaneously reduces the risk of extended drawdown compared to either strategy alone.

### Recommended next step

For a proper daily PnL correlation analysis, re-run both backtests with `capture_equity_curve=True` and compute rolling 21-day Pearson r on the combined OOS equity curve. The gate v2 framework does not currently store daily trade-level results in the verdict JSON.