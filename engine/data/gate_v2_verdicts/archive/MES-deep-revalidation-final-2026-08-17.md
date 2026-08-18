# MES Deep-Data Revalidation — Final Report (2026-08-17)

**Status: FINAL — delivered to Amo. PR #707 MERGED (2026-08-17T09:30:41Z, commit `707a76e`): RV filter is OFF in the paper vehicle.**

Data: `MES_2015-01-01_2026-08-16_1h.csv` — 42,826 hourly bars. **True span 2019-05-05 → 2026-08-14 (7.27y)**; the filename says 2015-01-01 but the cache starts 2019-05-05 (verified on disk 2026-08-17). Standard: deep data is the validation standard; shallow 2.3y Polygon caches no longer certify edge.

## Verdicts (deep, complete)

| Family | Verdict | pf_ci_lower | p_edge | DSR | WFO | MC 95th DD | OOS trades | Notes |
|---|---|---|---|---|---|---|---|---|
| **trend_rank11** (SMA 50/200 + 2.0×ATR) | **PASS (core)** | 1.14 | **0.9924** | 0.97 | MODERATE | 4.39% | **69** | **ONLY survivor on full history.** Core 4/4 (pf_ci≥1.1, p_edge≥0.95, DD≤5%, DSR≥0.1). ALT fails only on fixed_params_min_pf (0.93<1.2) + ALT DD ceiling (4.39>4.0). |
| trend_rv_filter (RV≥9%) | FAIL | 1.99 | 0.551 | 0.73 | WEAK | — | 58 | **RV filter degrades edge vs rank11 (0.992 → 0.551).** Filter now OFF in paper config (PR #707). |
| donchian rank1 | FAIL | 0.67 | 0.35 | 0.00 | WEAK | 5.65% | 287 | PF < 1 at every cost tier (realistic 0.67). |
| mean_reversion rank1 | FAIL | 0.68 | 0.37 | 0.141 | WEAK | 5.52% | 333 | BB+RSI rarely fires on MES 1h; bull-trend regime overwhelms mean-rev. |
| turn_of_month | FAIL | 1.565 | 0.50 | 0.57 | WEAK | 7.93% | 39 | PF 1.57 but DD over ALT ceiling (7.93% > 4%). |
| pre_fomc | INSUFFICIENT_SAMPLE | 1.064 | 0.40 | 0.071 | WEAK | 7.99% | 27 | Below DSR floor + DD ceiling; 27 trades < 30 min. |
| orb rank1 | FAIL | 0.34 | 0.10 | 0.00 | WEAK | 8.88% | 433 | Worst family tested; <10% of OOS windows profitable. |

*(rank11 row = live verdict `engine/data/gate_v2_verdicts/MES_trend_rank11.json`, created 2026-08-16T23:21Z. A 09:24 CDT refresh run re-confirmed PASS with marginally stronger metrics: p_edge 0.9968, pf_ci_lower 1.2714, DSR 0.9861, same 69 OOS — `archive/MES_trend_rank11_deep-2026-08-17-refresh.json`.)*

## Operational state — PR #707 (safety-review) MERGED

- **Change:** `engine/backtest/paper_config.py` — `MES_TREND_PAPER_CONFIG.sma_params.min_rv_annualized`: **9.0 → 0.0** (RV filter OFF). Params unchanged: fast=50, slow=200, atr_trail_mult=2.0, risk 0.25%, kill thresholds untouched. Verified on disk + import check.
- **Why:** the live vehicle previously ran the RV-filtered variant, which deep validation shows is the *weaker* edge (p_edge 0.55 vs 0.99). The tracked config now matches the only deep-validated champion.
- **Deploy follow-up (belt-and-suspenders):** `engine/.env` `MES_MIN_RV_ANNUALIZED=9.0` → `0.0` (or remove). The tracked change is the operative switch; the .env edit is not strictly required.
- **Rollback:** one-line revert; MES remains exempt from gate v2 verdict checks (Amo directive 2026-06-26 — MES is never disabled).
- Note: verdict-grid champion picked fast=60; paper vehicle runs fast=50. Both are inside the deep-validated family ([50,55,60]×[200] all PF≥1.35 on deep data), so no change needed.

## Reading

- **Only MES trend_rank11 (SMA 50/200 + 2.0×ATR) carries positive evidence on deep data.** All other MES families tested FAIL or are sample-insufficient against hard gates.
- ORB is the weakest (pf_ci 0.34, p_edge 0.10 — fewer than 10% of OOS windows profitable).
- Mean-rev hypothesis: MES bull-trend regime overwhelms mean-rev edge; candidate pivot = short-only fade variant, or abandon family.
- No new spend justified on donchian, mean-rev, calendar (turn_of_month / pre_fomc), or ORB.
- MGC remains halted/DO_NOT_TRADE; its deep verdicts also FAIL (live files 2026-08-16T22:11Z).

## Recommended next steps

1. **Watch the paper vehicle now that RV is OFF** — expect more/lower-volatility entries. Confirm live trade behavior matches the deep verdict over the next ~30 trades; no action unless live results contradict deep data.
2. **Make `_find_latest_cache` fallback loud** — the 2015-01-01 filename / 2019-05-05 true-start mismatch is a silent footgun. Warn (or fail) when a cache's actual span differs from its name.
3. **Investigate MGC 2829% drawdown** — MGC is DO_NOT_TRADE, but the number needs an explanation before any future MGC work is considered.
4. **Close out the failing MES families** — no further grid spend on donchian / mean-rev / turn_of_month / pre_fomc / ORB on the 1h MES cache. (Short-only mean-rev stays a research note, not a candidate.)
5. **Re-run rank11 deep verdict on each cache refresh** — the 09:24 refresh already re-confirmed PASS; keep the champion pinned to [50,55,60]×200 until a data refresh changes the verdict.

## Files

- Live verdicts: `engine/data/gate_v2_verdicts/MES_trend_rank11.json` (PASS), `.../MES_trend_rv_filter_rank1.json`, `.../MES_donchian_rank1.json`, `.../MES_meanrev_rank1.json`, `.../MES_turn_of_month.json`, `.../MES_pre_fomc.json`, `.../MES_orb_rank1.json`
- Deep archives: `engine/data/gate_v2_verdicts/archive/*_deep-2026-08-1[67].json`
- Interim report: `engine/data/gate_v2_verdicts/archive/MES-deep-revalidation-interim-2026-08-17.md`
- PR: https://github.com/mattamundson/jarvis-trader/pull/707 (merged 2026-08-17)
