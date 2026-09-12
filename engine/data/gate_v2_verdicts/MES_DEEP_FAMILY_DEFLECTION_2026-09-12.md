# MES Deep Family-Level Deflation — 2026-09-12

Scope: research-only; no live engine/risk/kill-switch/broker/paper_config changes.

## Method
- Family: 8 adjacent-grid sidecars generated from `fast=[55,60]`, `slow=[190,200]`, `ATR=[1.8,2.0]`.
- DSR approximation uses true trial count `8` and trade-level Sharpe recalculated from sidecar PnL.
- PBO approximation uses 8 chronological month groups; all 4-group test combinations (`70` folds).
- This is a screening/deflation artifact, not a runtime promotion gate by itself.

## DSR table
| Params | Trades | Total PnL | Trade Sharpe | DSR p(deflated) | DSR pass 5% |
|---|---:|---:|---:|---:|---|
| 60/200/2.0 | 122 | 11789.36 | 0.8777 | 1.0000 | False |
| 60/200/1.8 | 122 | 10793.27 | 0.7714 | 1.0000 | False |
| 55/190/2.0 | 127 | 8982.76 | 0.6633 | 1.0000 | False |
| 55/200/2.0 | 128 | 7445.58 | 0.5631 | 1.0000 | False |
| 55/190/1.8 | 127 | 7061.50 | 0.5290 | 1.0000 | False |
| 60/190/2.0 | 122 | 3586.98 | 0.2917 | 1.0000 | False |
| 60/190/1.8 | 122 | 2930.63 | 0.2347 | 1.0000 | False |
| 55/200/1.8 | 50 | -237.73 | -0.0289 | 1.0000 | False |

## PBO
| Folds | PBO | Interpretation |
|---:|---:|---|
| 70 | 0.3714 | fraction of train-selected winners ranking below median OOS |

Selection counts:
- `55/190/1.8` selected in `9` / `70` folds
- `55/190/2.0` selected in `2` / `70` folds
- `55/200/1.8` selected in `1` / `70` folds
- `55/200/2.0` selected in `6` / `70` folds
- `60/190/1.8` selected in `1` / `70` folds
- `60/200/1.8` selected in `20` / `70` folds
- `60/200/2.0` selected in `31` / `70` folds

## Verdict
Best aggregate remains 60/200/2.0, but family-level deflation is not clean promotion evidence; PBO and non-significant paired tests keep status at robustness support only.

## Next actions
1. Keep `60/200/2.0` labeled as best point estimate / robustness support only.
2. Do not change runtime MES params without [safety-review].
3. Commit this research lane artifact set after final git status review.
