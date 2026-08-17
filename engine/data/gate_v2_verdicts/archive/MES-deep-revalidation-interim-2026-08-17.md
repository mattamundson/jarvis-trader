# MES Deep-Data Revalidation — Interim Report (2026-08-17)

Data: `MES_2015-01-01_2026-08-16_1h.csv` (7.3y, 42k+ bars, Databento/IBKR deep cache)
Standard: deep data is the validation standard; shallow 2.3y Polygon caches no longer certify edge.

## Completed verdicts (deep)

| Family | Verdict | pf_ci_lower | p_edge | DSR | WFO | MC 95th DD | OOS trades | Notes |
|---|---|---|---|---|---|---|---|---|
| **trend rank11** (prev) | **PASS** | 1.14 | 0.992 | 0.97 | STRONG | 0.81% | 69 | ONLY survivor on full history |
| trend rv_filter (prev) | FAIL | — | 0.551 | — | — | — | 58 | filter degrades edge vs rank11 |
| donchian rank1 | FAIL | 0.67 | 0.35 | 0.0 | WEAK | 5.65% | 22 (realistic) | PF < 1 at every cost tier |
| mean_reversion rank1 | FAIL | 0.68 | — | 0.141 | WEAK | 5.52% | 0 (BB+RSI) | signal doesn't fire on MES 1h; trend regime overwhelms mean-rev |
| turn_of_month | FAIL | 1.565 | 0.5 | 0.57 | — | 7.93% | 39 | dd over ALT ceiling |
| pre_fomc | INSUFFICIENT_SAMPLE | 1.064 | 0.4 | 0.071 | WEAK | 7.99% | 27 | below dsr floor + dd ceiling |
| orb rank1 | **FAIL** | 0.34 | 0.10 | 0.0 | WEAK | 8.88% | 433 | worst family tested; regime instability |

## Reading

- **Only MES trend_rank11 (SMA 50/200 + 2.0×ATR) carries positive evidence on deep data.**
- Every other family tested fails one or more hard gates (DSR < floor, MC DD > 4–5%, WFO WEAK, PF ≤ 1).
- Mean-rev: signal never fires on MES 1h (0 OOS trades); candidate pivot = short-only fade variant, or abandon family.
- ORB verdict pending (background job `proc_ab891ee5cce9`, notify on completion).

## Files

- Verdicts live in `wt-deep-reval-20260817/engine/data/gate_v2_verdicts/`
- Archive copy on master: `engine/data/gate_v2_verdicts/archive/*deep-2026-08-16.json` (trend/rv_filter/MGC)
- Remaining to archive: donchian, mean_reversion, turn_of_month, pre_fomc, orb (once done) with `-deep-2026-08-17` suffix.
