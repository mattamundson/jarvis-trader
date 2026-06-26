# Vol-Targeting Uplift Experiment — SMA Trend Strategy

Compares fixed-size (1 contract) vs vol-targeted position sizing on the
SMA-trend strategy. Weight = clip(target_vol / rv_at_entry, 0, 3); target_vol
= median realized-vol at all entry bars for the symbol.

## Results

| Symbol | Mode | Trades | PF | Sharpe | MaxDD $ |
|--------|----------|--------|-------|--------|---------|
| MGC | fixed | 54 | 1.803 | 1.077 | 1,373 |
| MGC | vol-target | 54 | 2.252 | 1.659 | 519 |
| ZN | fixed | 9 | 0.000 | -25.295 | 1,291 |
| ZN | vol-target | 9 | 0.000 | -16.518 | 1,330 |
| ZB | fixed | 6 | 0.000 | -19.367 | 1,672 |
| ZB | vol-target | 6 | 0.000 | -13.916 | 1,681 |

## Symbol metadata

**MGC**: `MGC_2024-04-26_2026-05-20_1h.csv` | 754 days | multiplier=10.0 | target_vol=13.32%  
  Delta: PF +0.449, Sharpe +0.582, MaxDD $-854

**ZN**: `ZN_2025-06-18_2026-06-18_1h.csv` | 364 days | multiplier=1000.0 | target_vol=3.66%  
  Delta: PF +0.000, Sharpe +8.777, MaxDD $+39

**ZB**: `ZB_2025-06-18_2026-06-18_1h.csv` | 364 days | multiplier=1000.0 | target_vol=8.46%  
  Delta: PF +0.000, Sharpe +5.452, MaxDD $+8

## Verdict

Vol-targeting improved Profit Factor in 1/3 symbols, Sharpe in 3/3, and reduced MaxDD in 1/3.
Consistent improvement across all three metrics requires 3/3 in each row.
**Recommendation: MIXED signal -- do not promote to production without deeper WFO study**
