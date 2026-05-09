# Diversification Audit — MES Rank11 vs MGC Rank4

*Generated 2026-05-09 10:34 UTC*

## Methodology

Window-level OOS PF values are aligned by OOS start month and compared. MES rank11 uses 1-month OOS windows; MGC rank4 uses 2-month OOS windows. Months where only one strategy has a window are excluded from the correlation calculation (inner join on start month).

**Limitation:** This proxy uses per-window aggregate PF, not daily equity curves. True daily PnL correlation would require re-running backtests with a `--export-daily-pnl` flag (not yet implemented). This audit is a conservative first-pass — aggregate PF correlation tends to *overstate* true correlation vs daily PnL correlation.

## Window-Level OOS PF Comparison

| Month | MES PF | MES trades | MES | MGC PF | MGC trades | MGC | Both |
|-------|--------|------------|-----|--------|------------|-----|------|
| 2024-10 | 0.000 | 1 | FAIL | 0.023 | 5 | FAIL | - |
| 2024-11 | 0.000 | 0 | FAIL | 0.274 | 5 | FAIL | - |
| 2024-12 | inf | 1 | PASS | 0.749 | 7 | FAIL | opp |
| 2025-01 | inf | 1 | PASS | 0.751 | 5 | FAIL | opp |
| 2025-02 | inf | 1 | PASS | 3.788 | 3 | PASS | both |
| 2025-03 | inf | 1 | PASS | 3.884 | 4 | PASS | both |
| 2025-04 | 0.000 | 0 | FAIL | 19.111 | 4 | PASS | opp |
| 2025-05 | 0.737 | 2 | FAIL | inf | 4 | PASS | opp |
| 2025-06 | 0.000 | 0 | FAIL | 6.042 | 4 | PASS | opp |
| 2025-07 | inf | 1 | PASS | 666.780 | 3 | PASS | both |
| 2025-08 | 0.000 | 0 | FAIL | 295.530 | 2 | PASS | opp |
| 2025-09 | inf | 1 | PASS | 5.994 | 4 | PASS | both |
| 2025-10 | inf | 2 | PASS | 8.357 | 5 | PASS | both |
| 2025-11 | inf | 2 | PASS | 4.540 | 3 | PASS | both |
| 2025-12 | 0.000 | 0 | FAIL | inf | 2 | PASS | opp |
| 2026-01 | 1.644 | 2 | PASS | inf | 1 | PASS | both |
| 2026-02 | 0.000 | 1 | FAIL | 0.000 | 1 | FAIL | - |
| 2026-03 | 0.000 | 0 | FAIL | 0.171 | 2 | FAIL | - |
| 2026-04 | 0.000 | 0 | FAIL | inf | 1 | PASS | opp |

## Statistics

- **Aligned windows:** 19
- **Both profitable:** 7/19 (37%)
- **MES only profitable:** 2/19 (11%)
- **MGC only profitable:** 6/19 (32%)
- **Neither profitable:** 4/19 (21%)
- **Opposite direction (one PASS, one FAIL):** 8/19 (42%)

**OOS PF Pearson correlation:** r = 0.128 → LOW — genuine diversification

## Verdict

MES trend (equity-index) and MGC trend (gold) are **lowly correlated** at the OOS window level. Running both simultaneously provides genuine portfolio diversification — each strategy covers months the other cannot.

## Next Step for Deeper Audit

For a daily equity-curve correlation: add `--export-daily-pnl <path>` to each WFO runner and rerun. Compute Pearson r on the overlapping daily PnL series. Window-level aggregate PF tends to overstate correlation vs daily PnL, so the true daily r is likely at or below the r computed here.