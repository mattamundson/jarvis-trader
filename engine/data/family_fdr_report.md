# Family-wide BH-FDR — jarvis gate-v2 campaign

- Verdicts total: **38**  |  FDR family (have OOS data): **34**  |  excluded (no OOS data): **4**
- gate-v2 PASS: **3**  |  survive family BH-FDR (q=0.1) AND gate-PASS = **ROBUST_EDGE: 0**

Primary p-value = binomial sign-test on OOS-window profitability. `robust_edge` = gate-v2 PASS AND survives the primary family BH line.

| id | gate | pf_ci_lo | p_edge | n_oos | p_binom | BH-binom | p_dsr | BH-dsr | ROBUST |
|---|---|---|---|---|---|---|---|---|---|
| MGC_trend_rv_filter_rank1 | PASS | 3.182 | 1.000 | 7 | 0.0078 | · | 0.0000 | Y | · |
| MES_trend_rank11 | INSUFFICIENT_SAMPLE | 2.500 | 0.750 | 19 | 0.0318 | · | 0.0000 | Y | · |
| MES_trend_rv_filter_rank2 | INSUFFICIENT_SAMPLE | 1.905 | 0.833 | 7 | 0.0625 | · | 0.0000 | Y | · |
| MGC_trend_rank4 | PASS | 2.597 | 0.684 | 19 | 0.0835 | · | 0.0000 | Y | · |
| MES_trend_adx_filter_rank1 | FAIL | 1.434 | 0.625 | 19 | 0.1796 | · | 1.0000 | · | · |
| MGC_trend_adx_filter_rank1 | PASS | 1.977 | 0.611 | 19 | 0.1796 | · | 0.0000 | Y | · |
| MES_trend_vix_rank1 | FAIL | 1.796 | 0.583 | 19 | 0.3238 | · | 1.0000 | · | · |
| MES_trend_vix_rank2 | FAIL | 1.796 | 0.583 | 19 | 0.3238 | · | 1.0000 | · | · |
| MCL_trend_adx_filter_rank1 | FAIL | 0.697 | 0.500 | 7 | 0.5000 | · | 0.0000 | Y | · |
| MES_gap_fade_rank1 | FAIL | 0.544 | 0.600 | 5 | 0.5000 | · | 1.0000 | · | · |
| MES_ib_go_rank1 | FAIL | 0.871 | 0.600 | 5 | 0.5000 | · | 0.9999 | · | · |
| MES_trend_adx_rv_filter_rank1 | FAIL | 0.000 | 0.500 | 19 | 0.5000 | · | 0.7229 | · | · |
| MES_trend_vix_rank3 | FAIL | 0.871 | 0.500 | 7 | 0.5000 | · | 0.0000 | Y | · |
| MGC_ib_go_rank1 | FAIL | 0.857 | 0.571 | 7 | 0.5000 | · | 1.0000 | · | · |
| MGC_trend_adx_rv_filter_rank1 | FAIL | 1.631 | 0.526 | 19 | 0.5000 | · | 0.0277 | · | · |
| MNQ_trend_adx_filter_rank1 | FAIL | 0.958 | 0.571 | 7 | 0.5000 | · | 1.0000 | · | · |
| MNQ_trend_rv_filter_rank1 | FAIL | 0.786 | 0.571 | 7 | 0.5000 | · | 0.3235 | · | · |
| MES_trend_15m_rank1 | FAIL | 0.731 | 0.500 | 18 | 0.5927 | · | 1.0000 | · | · |
| M2K_trend_adx_filter_rank1 | FAIL | 0.618 | 0.500 | 6 | 0.6562 | · | 1.0000 | · | · |
| M2K_trend_rank3 | FAIL | 0.465 | 0.500 | 6 | 0.6562 | · | 1.0000 | · | · |
| MGC_gap_fade_rank1 | FAIL | 0.497 | 0.429 | 7 | 0.7734 | · | 1.0000 | · | · |
| MGC_gap_go_rank1 | FAIL | 0.490 | 0.429 | 7 | 0.7734 | · | 1.0000 | · | · |
| MGC_tpo_breakout_rank1 | FAIL | 0.430 | 0.429 | 7 | 0.7734 | · | 1.0000 | · | · |
| MGC_tpo_reversion_rank1 | FAIL | 0.778 | 0.429 | 7 | 0.7734 | · | 1.0000 | · | · |
| MES_tpo_reversion_trend_rank1 | FAIL | 0.491 | 0.400 | 5 | 0.8125 | · | 1.0000 | · | · |
| MES_donchian_rank1 | FAIL | 0.680 | 0.368 | 19 | 0.9165 | · | 1.0000 | · | · |
| MES_meanrev_rank2 | FAIL | 0.691 | 0.368 | 19 | 0.9165 | · | 1.0000 | · | · |
| MES_tpo_breakout_rank1 | FAIL | 0.396 | 0.200 | 5 | 0.9688 | · | 1.0000 | · | · |
| MES_tpo_breakout_trend_rank1 | FAIL | 0.507 | 0.200 | 5 | 0.9688 | · | 1.0000 | · | · |
| MES_tpo_reversion_rank1 | FAIL | 0.050 | 0.200 | 5 | 0.9688 | · | 1.0000 | · | · |
| MGC_ib_fade_rank1 | FAIL | 0.317 | 0.143 | 7 | 0.9922 | · | 1.0000 | · | · |
| MES_confluence_rank1 | FAIL | 0.255 | 0.154 | 15 | 0.9995 | · | 1.0000 | · | · |
| MES_gap_go_rank1 | FAIL | 0.583 | 0.000 | 5 | 1.0000 | · | 1.0000 | · | · |
| MES_ib_fade_rank1 | FAIL | 0.365 | 0.000 | 5 | 1.0000 | · | 1.0000 | · | · |

## Excluded (no OOS-window data — no family p-value)

- `MCL_meanrev_rank1` (gate=FAIL) — no OOS-window data (cannot compute family p-value)
- `MCL_meanrev_regime_rank1` (gate=FAIL) — no OOS-window data (cannot compute family p-value)
- `MES_trend_rank7` (gate=PASS) — no OOS-window data (cannot compute family p-value)
- `MNQ_trend_rank1` (gate=FAIL) — no OOS-window data (cannot compute family p-value)

## Honest read

- **0** strategies are both gate-v2 PASS and survive the whole-campaign BH-FDR. 
- With only 5–19 non-overlapping OOS windows per strategy the binomial sign-test is deliberately conservative; a strict BH line over a 34-member family can reject strong-PF strategies on window count alone. The ranking (lowest `p_binom` first) shows which strategies are *closest* to robust — that is where real edge, if any, lives.
- This correction can only SHRINK the validated set. A NO survivor result is the honest outcome of screening many candidates with few OOS windows, not proof that no edge exists.
