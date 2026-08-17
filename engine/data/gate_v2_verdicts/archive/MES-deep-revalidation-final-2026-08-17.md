# MES Deep-Data Revalidation — Final Report (2026-08-17)

Data: `MES_2015-01-01_2026-08-16_1h.csv` (7.3y, Databento/IBKR deep cache)
Standard: deep data is the validation standard; shallow 2.3y Polygon caches no longer certify edge.

## Verdicts (deep, complete)

| Family | Verdict | pf_ci_lower | p_edge | DSR | WFO | MC 95th DD | OOS trades | Notes |
|---|---|---|---|---|---|---|---|---|
| **trend rank11** (prior) | **PASS** | 1.14 | 0.992 | 0.97 | STRONG | 0.81% | 69 | **ONLY survivor on full history** |
| trend rv_filter (prior) | FAIL | — | 0.551 | — | — | — | 58 | filter degrades edge vs rank11 (0.992→0.551) |
| donchian rank1 | FAIL | 0.67 | 0.35 | 0.0 | WEAK | 5.65% | 287 | PF < 1 at every cost tier |
| mean_reversion rank1 | FAIL | 0.68 | 0.37 | 0.141 | WEAK | 5.52% | 333 | BB+RSI rarely fires on MES 1h; trend regime overwhelms mean-rev |
| turn_of_month | FAIL | 1.565 | 0.5 | 0.57 | — | 7.93% | 39 | DD over ALT ceiling |
| pre_fomc | INSUFFICIENT_SAMPLE | 1.064 | 0.4 | 0.071 | WEAK | 7.99% | 27 | below dsr floor + dd ceiling |
| orb rank1 | FAIL | 0.34 | 0.10 | 0.0 | WEAK | 8.88% | 433 | worst family tested; regime instability |

## Reading

- **Only MES trend_rank11 (SMA 50/200 + 2.0×ATR) carries positive evidence on deep data.** All other MES families tested FAIL one or more hard gates.
- ORB is the weakest (pf_ci 0.34, p_edge 0.10 — fewer than 10% of OOS windows profitable).
- Mean-rev hypothesis: MES bull-trend regime overwhelms mean-rev edge; candidate pivot = short-only fade variant, or abandon family.
- No new spend justified on donchian, mean-rev, calendar (turn_of_month/pre_fomc), or ORB.

## Files

- Verdicts archived on master: `engine/data/gate_v2_verdicts/archive/MES_{donchian_rank1,meanrev_rank1,turn_of_month,pre_fomc,orb_rank1}_deep-2026-08-17.json`
- Interim report: `engine/data/gate_v2_verdicts/archive/MES-deep-revalidation-interim-2026-08-17.md`
- Worktree `wt-deep-reval-20260817` holds working copies (can be removed after archive).
