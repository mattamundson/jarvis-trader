# Family-wide BH-FDR — jarvis gate-v2 campaign

- Verdicts total: **57**  |  FDR family (have OOS data): **50**  |  excluded (no OOS data): **7**
- gate-v2 PASS: **4**  |  survive family BH-FDR (q=0.1) AND gate-PASS = **ROBUST_EDGE: 0**

Primary p-value = binomial sign-test on OOS-window profitability. `robust_edge` = gate-v2 PASS AND survives the primary family BH line.

| id | gate | pf_ci_lo | p_edge | n_oos | oos_tr | adq | med_tr/win | thin | pwadq | p_binom | BH-binom | p_dsr | BH-dsr | ROBUST |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MGC_trend_rv_filter_rank1 | PASS | 3.182 | 1.000 | 7 | 26 | **n** | 4 | 5 | **n** | 0.0078 | · | 0.0000 | Y | · |
| MES_trend_rv_filter_rank2 | INSUFFICIENT_SAMPLE | 1.905 | 0.833 | 7 | 16 | **n** | 2 | 7 | **n** | 0.0625 | · | 0.0000 | Y | · |
| MGC_trend_rank4 | PASS | 2.597 | 0.684 | 19 | 67 | Y | 4 | 14 | **n** | 0.0835 | · | 0.0000 | Y | · |
| MES_trend_adx_filter_rank1 | FAIL | 1.434 | 0.625 | 19 | 42 | Y | 2 | 19 | **n** | 0.1796 | · | 1.0000 | · | · |
| MGC_trend_adx_filter_rank1 | PASS | 1.977 | 0.611 | 19 | 39 | Y | 2 | 18 | **n** | 0.1796 | · | 0.0000 | Y | · |
| MGC_singlefinder_fill_rank1 | PASS | 1.050 | 0.714 | 7 | 381 | Y | 60 | 0 | Y | 0.2266 | · | 0.0000 | Y | · |
| MES_trend_vix_rank2 | FAIL | 1.796 | 0.583 | 19 | 15 | **n** | 1 | 19 | **n** | 0.3238 | · | 1.0000 | · | · |
| MCL_trend_adx_filter_rank1 | FAIL | 0.697 | 0.500 | 7 | 14 | **n** | 2 | 7 | **n** | 0.5000 | · | 0.0000 | Y | · |
| MES_gap_fade_rank1 | FAIL | 0.544 | 0.600 | 5 | 126 | Y | 22 | 0 | Y | 0.5000 | · | 1.0000 | · | · |
| MES_ib_go_rank1 | FAIL | 0.871 | 0.600 | 5 | 189 | Y | 40 | 0 | Y | 0.5000 | · | 0.9999 | · | · |
| MES_rangefinder_breakout_rank1 | FAIL | 0.769 | 0.600 | 5 | 303 | Y | 64 | 0 | Y | 0.5000 | · | 1.0000 | · | · |
| MES_singlefinder_fill_rank1 | FAIL | 0.707 | 0.600 | 5 | 290 | Y | 60 | 0 | Y | 0.5000 | · | 1.0000 | · | · |
| MES_trend_adx_rv_filter_rank1 | FAIL | 0.000 | 0.500 | 19 | 6 | **n** | 0 | 19 | **n** | 0.5000 | · | 0.7229 | · | · |
| MES_trend_vix_rank3 | FAIL | 0.871 | 0.500 | 7 | 22 | **n** | 3 | 6 | **n** | 0.5000 | · | 0.0000 | Y | · |
| MES_tscore_reversion_rank1 | FAIL | 0.751 | 0.600 | 5 | 288 | Y | 60 | 0 | Y | 0.5000 | · | 1.0000 | · | · |
| MGC_ib_go_rank1 | FAIL | 0.857 | 0.571 | 7 | 103 | Y | 16 | 1 | Y | 0.5000 | · | 1.0000 | · | · |
| MGC_rangefinder_breakout_rank1 | FAIL | 0.798 | 0.571 | 7 | 313 | Y | 49 | 0 | Y | 0.5000 | · | 1.0000 | · | · |
| MGC_trend_adx_rv_filter_rank1 | FAIL | 1.631 | 0.526 | 19 | 41 | Y | 2 | 19 | **n** | 0.5000 | · | 0.0277 | · | · |
| MGC_tscore_trend_rank1 | FAIL | 0.963 | 0.571 | 7 | 295 | Y | 42 | 0 | Y | 0.5000 | · | 0.3406 | · | · |
| MNQ_trend_adx_filter_rank1 | FAIL | 0.958 | 0.571 | 7 | 32 | Y | 5 | 3 | Y | 0.5000 | · | 1.0000 | · | · |
| MNQ_trend_rv_filter_rank1 | FAIL | 0.786 | 0.571 | 7 | 42 | Y | 7 | 2 | Y | 0.5000 | · | 0.3235 | · | · |
| MES_trend_15m_rank1 | FAIL | 0.731 | 0.500 | 18 | 393 | Y | 17 | 0 | Y | 0.5927 | · | 1.0000 | · | · |
| M2K_trend_adx_filter_rank1 | FAIL | 0.618 | 0.500 | 6 | 25 | **n** | 4 | 4 | **n** | 0.6562 | · | 1.0000 | · | · |
| M2K_trend_rank3 | FAIL | 0.465 | 0.500 | 6 | 41 | Y | 7 | 2 | Y | 0.6562 | · | 1.0000 | · | · |
| MES_trend_rank11 | INSUFFICIENT_SAMPLE | 0.932 | 0.429 | 20 | 17 | **n** | 1 | 20 | **n** | 0.7483 | · | 0.0000 | Y | · |
| MGC_gap_fade_rank1 | FAIL | 0.497 | 0.429 | 7 | 131 | Y | 19 | 0 | Y | 0.7734 | · | 1.0000 | · | · |
| MGC_gap_go_rank1 | FAIL | 0.490 | 0.429 | 7 | 183 | Y | 26 | 0 | Y | 0.7734 | · | 1.0000 | · | · |
| MGC_tpo_breakout_rank1 | FAIL | 0.430 | 0.429 | 7 | 169 | Y | 26 | 0 | Y | 0.7734 | · | 1.0000 | · | · |
| MGC_tpo_reversion_rank1 | FAIL | 0.778 | 0.429 | 7 | 197 | Y | 26 | 0 | Y | 0.7734 | · | 1.0000 | · | · |
| MES_tpo_reversion_trend_rank1 | FAIL | 0.491 | 0.400 | 5 | 93 | Y | 19 | 0 | Y | 0.8125 | · | 1.0000 | · | · |
| MES_donchian_rank1 | FAIL | 0.680 | 0.368 | 19 | 259 | Y | 14 | 0 | Y | 0.9165 | · | 1.0000 | · | · |
| MES_meanrev_rank2 | FAIL | 0.691 | 0.368 | 19 | 208 | Y | 10 | 1 | Y | 0.9165 | · | 1.0000 | · | · |
| MGC_rangefinder_fade_rank1 | FAIL | 0.515 | 0.286 | 7 | 267 | Y | 40 | 0 | Y | 0.9375 | · | 1.0000 | · | · |
| MGC_tscore_reversion_rank1 | FAIL | 0.717 | 0.286 | 7 | 221 | Y | 33 | 0 | Y | 0.9375 | · | 1.0000 | · | · |
| MES_trend_vix_rank1 | FAIL | 0.600 | 0.357 | 20 | 16 | **n** | 1 | 20 | **n** | 0.9423 | · | 1.0000 | · | · |
| MES_tpo_breakout_rank1 | FAIL | 0.396 | 0.200 | 5 | 86 | Y | 17 | 0 | Y | 0.9688 | · | 1.0000 | · | · |
| MES_tpo_breakout_trend_rank1 | FAIL | 0.507 | 0.200 | 5 | 86 | Y | 19 | 0 | Y | 0.9688 | · | 1.0000 | · | · |
| MES_tpo_reversion_rank1 | FAIL | 0.050 | 0.200 | 5 | 95 | Y | 7 | 0 | Y | 0.9688 | · | 1.0000 | · | · |
| MES_tscore_trend_rank1 | FAIL | 0.629 | 0.200 | 5 | 266 | Y | 56 | 0 | Y | 0.9688 | · | 1.0000 | · | · |
| MGC_gapfinder_fill_rank1 | INSUFFICIENT_SAMPLE | 0.018 | 0.200 | 7 | 16 | **n** | 2 | 6 | **n** | 0.9922 | · | 1.0000 | · | · |
| MGC_ib_fade_rank1 | FAIL | 0.317 | 0.143 | 7 | 117 | Y | 17 | 0 | Y | 0.9922 | · | 1.0000 | · | · |
| MES_confluence_rank1 | FAIL | 0.255 | 0.154 | 15 | 67 | Y | 5 | 6 | Y | 0.9995 | · | 1.0000 | · | · |
| M6B_trend_diversifier | INSUFFICIENT_SAMPLE | 0.000 | 0.000 | 6 | 6 | **n** | 1 | 6 | **n** | 1.0000 | · | 0.9538 | · | · |
| M6E_trend_diversifier | INSUFFICIENT_SAMPLE | 0.000 | 0.000 | 6 | 6 | **n** | 1 | 6 | **n** | 1.0000 | · | 0.9986 | · | · |
| MES_gap_go_rank1 | FAIL | 0.583 | 0.000 | 5 | 82 | Y | 17 | 0 | Y | 1.0000 | · | 1.0000 | · | · |
| MES_gapfinder_fill_rank1 | INSUFFICIENT_SAMPLE | 0.000 | 0.000 | 1 | 0 | **n** | 0 | 1 | **n** | 1.0000 | · | 0.9974 | · | · |
| MES_ib_fade_rank1 | FAIL | 0.365 | 0.000 | 5 | 180 | Y | 37 | 0 | Y | 1.0000 | · | 1.0000 | · | · |
| MES_rangefinder_fade_rank1 | FAIL | 0.225 | 0.000 | 5 | 305 | Y | 64 | 0 | Y | 1.0000 | · | 1.0000 | · | · |
| ZB_trend_diversifier | INSUFFICIENT_SAMPLE | 0.000 | 0.000 | 6 | 23 | **n** | 4.5 | 3 | **n** | 1.0000 | · | 1.0000 | · | · |
| ZN_trend_diversifier | INSUFFICIENT_SAMPLE | 0.000 | 0.000 | 6 | 20 | **n** | 3.5 | 6 | **n** | 1.0000 | · | 1.0000 | · | · |

## Excluded (no OOS-window data — no family p-value)

- `MCL_meanrev_rank1` (gate=FAIL) — no OOS-window data (cannot compute family p-value)
- `MCL_meanrev_regime_rank1` (gate=FAIL) — no OOS-window data (cannot compute family p-value)
- `MES_meanrev_rank1` (gate=FAIL) — no OOS-window data (cannot compute family p-value)
- `MES_trend_rank7` (gate=PASS) — no OOS-window data (cannot compute family p-value)
- `MGC_meanrev_rank1` (gate=FAIL) — no OOS-window data (cannot compute family p-value)
- `MNQ_meanrev_rank1` (gate=FAIL) — no OOS-window data (cannot compute family p-value)
- `MNQ_trend_rank1` (gate=FAIL) — no OOS-window data (cannot compute family p-value)

## Honest read

- **0** strategies are both gate-v2 PASS and survive the whole-campaign BH-FDR. 
- With only 5–19 non-overlapping OOS windows per strategy the binomial sign-test is deliberately conservative; a strict BH line over a 50-member family can reject strong-PF strategies on window count alone. The ranking (lowest `p_binom` first) shows which strategies are *closest* to robust — but read it together with `adq`.
- **`adq` = sample adequacy** (total OOS trades >= 30). An `adq=n` row is a small-sample mirage: its p_binom/PF can look strong while resting on a handful of OOS trades (PF inflated by 2-trade windows). Such a row can rank high on p_binom yet is **not** where durable edge lives, and it can never be certified `ROBUST` regardless of the BH line. Treat the lowest-p_binom `adq=Y` row as the genuine lead.
- **`pwadq` = per-window adequacy** (MEDIAN window >= 5 OOS trades; `med_tr/win` and `thin` = count of windows below that floor). The aggregate `adq` floor is necessary but NOT sufficient: a strategy can clear 30 aggregate trades while most windows are 1-4 trades with degenerate PFs (inf/666/295) — `pwadq=n` flags exactly that. A `pwadq=n` row can never be `ROBUST` even if `adq=Y` (e.g. `trend_rank4`: 67 aggregate trades, median 4/window, 14 of 19 windows thin). `pwadq=?` means no per-window data (fails open — the aggregate floor still applies).
- This correction can only SHRINK the validated set. A NO survivor result is the honest outcome of screening many candidates with few OOS windows, not proof that no edge exists.
