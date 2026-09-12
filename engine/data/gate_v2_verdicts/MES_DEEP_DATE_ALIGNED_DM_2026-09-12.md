# MES Deep Date-Aligned DM — 2026-09-12

Scope: research-only; no live engine/risk/kill-switch/broker/paper_config changes.

## Method
- Aggregate trade PnL by `exit_date[:10]` calendar day.
- Inner-join common exit days.
- DM power=1 on daily PnL score; **negative DM_HLN favors A**, positive favors B.
- Raw timestamp-alignment is demoted because duplicate exit timestamps can collapse in map-based joins.

## Results
| A | B | join days | A join pnl | B join pnl | DM_HLN | p(two-sided) | Read |
|---|---|---:|---:|---:|---:|---:|---|
| 60/200/2.0 | 60/200/1.8 | 94 | 13995.64 | 10793.27 | -0.8490 | 0.3980 | A better directionally; not significant at 5% |
| 60/200/2.0 | 55/190/2.0 | 70 | 7625.19 | 8240.00 | 0.1679 | 0.8671 | B better directionally; not significant at 5% |
| 60/200/1.8 | 55/190/2.0 | 67 | 6731.49 | 8196.26 | 0.6419 | 0.5232 | B better directionally; not significant at 5% |

## Duplicate timestamp diagnostics
| Params | trades | unique exit timestamps | duplicate timestamp keys | max same timestamp |
|---|---:|---:|---:|---:|
| 60/200/2.0 | 122 | 101 | 1 | 22 |
| 60/200/1.8 | 122 | 94 | 1 | 29 |
| 55/190/2.0 | 127 | 100 | 1 | 28 |

## Verdict
Date/daily-aligned evidence is mixed and overlap-specific. `60/200/2.0` remains best aggregate on the full sample, but daily-aligned paired tests do not create clean promotion evidence. Maintain verdict: robustness support only; no runtime/config change without further family-level deflation and [safety-review].
