# DM Screen Results — First Run (2026-09-10)

Tool: `engine/backtest/dm_edge_screen.py` (research lane, offline). Golden-vector tests: 6/6 PASS incl. scipy t-parity <1e-8.

## Finding 1: MES trend (rank11) vs MES STC-trend meta (rank1) — oos_pf, power=1

| Stat | Value |
|---|---|
| Aligned OOS windows | 15 |
| d̄ (loss diff, A−B) | +0.826 |
| DM (HLN-corrected) | **2.93** |
| p (two-sided) | **0.011** |

**Interpretation:** the STC-trend meta candidate has significantly HIGHER OOS PF than the SMA trend champion (loss_A > loss_B, positive DM). At the 5% level, B is better — and this is exactly the kind of comparison the 2026-09-02 rank11 refresh context needed: rank11 FAILed, and the replacement candidate was dismissed partly on absolute criteria. The DM screen shows the replacement was not merely "different noise" — its PF advantage over the incumbent is statistically distinguishable (p≈0.011), even though both FAIL absolute gate v2.
- Caveat: n=15 windows, PF distribution heavy-tailed; power=1 (absolute loss) chosen over squared to limit outlier leverage. On oos_sharpe (power=2) the difference is NOT significant (DM −1.04, p=0.31) — the two candidates' Sharpe streams are statistically indistinguishable.
- Net: PF advantage is significant; risk-adjusted (Sharpe) advantage is not. Consistent with meta-labeling raising PF via trade selection without changing per-trade risk profile.

## Finding 2: trend_rank11 param-neighborhood (fixed_params_min_pf defect)

| Combo | PF | Trades |
|---|---|---|
| **60/200/2.0 (champion)** | **1.5275** | 33 |
| 55/200/2.0 | 1.3202 | 36 |
| 50/200/2.0 | 0.6989 | 37 |

Champion's ±5-fast neighbors straddle the 1.2 alt floor. The 50/200 neighbor (PF 0.70) is what floors `fixed_params_min_pf` at 0.70 — the rank11 FAIL. This is the param-sensitivity signature the DM screen was built to quantify: with only aggregate per-combo PF (no per-trade streams in the verdict JSON), a formal DM between champion and neighbors requires re-running the backtest with trade-level logging. **Recommended follow-up:** add per-trade OOS PnL capture to `iterate.py` output so DM can run at trade level (the correct granularity), not window level.

## Cross-symbol note
MES vs MGC window alignment failed (only 1 shared oos_period — different WFO schedules). DM comparisons require identical OOS calendars; documented as a tool limitation.

## Conclusions for the campaign
1. The DM screen is live and validated; it already produced a non-obvious result (STC-trend meta PF edge is real, Sharpe edge is not).
2. Window-level DM is coarse; trade-level capture in iterate.py is the ~0.5-day follow-up that makes the screen definitive for param-band robustness.
3. No engine config change is implied by this run — [safety-review] PR not triggered.
