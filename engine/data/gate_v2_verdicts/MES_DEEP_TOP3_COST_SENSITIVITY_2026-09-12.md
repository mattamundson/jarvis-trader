# MES Deep Top-3 Cost Sensitivity — 2026-09-12

Scope: research-only; no live engine/risk/kill-switch/broker/`.env`/`paper_config.py`/symbol-gate changes.

## Method
- Cache: `MES_2019-05-05_2026-08-26_1h.csv`
- Cache SHA256: `e26631c012b128284e61526dad78e7d39a3c180634dad7398a7dd8cc225f83fe`
- Span years: `7.3073`
- Extra cost model: subtract `extra_ticks × $1.25 × contracts` from each historical trade PnL.
- Tested rows: `60/200/2.0`, `60/200/1.8`, `55/190/2.0`.

## Sensitivity table
| Params | Extra ticks/contract | Trades | Total PnL | PF | Sharpe | CAGR % | p_edge | PF 95% low |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 60/200/2.0 | 0 | 122 | 11789.36 | 1.6952 | 0.8777 | 2.9385 | 0.9935 | 1.1109 |
| 60/200/2.0 | 1 | 122 | 11085.61 | 1.6401 | 0.8248 | 2.7773 | 0.9910 | 1.0763 |
| 60/200/2.0 | 2 | 122 | 10381.86 | 1.5871 | 0.7720 | 2.6145 | 0.9765 | 1.0098 |
| 60/200/1.8 | 0 | 122 | 10793.27 | 1.5778 | 0.7714 | 2.7099 | 0.9735 | 0.9940 |
| 60/200/1.8 | 1 | 122 | 10003.27 | 1.5245 | 0.7146 | 2.5262 | 0.9730 | 0.9913 |
| 60/200/1.8 | 2 | 122 | 9213.27 | 1.4732 | 0.6578 | 2.3405 | 0.9670 | 0.9758 |
| 55/190/2.0 | 0 | 127 | 8982.76 | 1.5033 | 0.6633 | 2.2859 | 0.9615 | 0.9462 |
| 55/190/2.0 | 1 | 127 | 8276.51 | 1.4542 | 0.6111 | 2.1175 | 0.9495 | 0.9346 |
| 55/190/2.0 | 2 | 127 | 7570.26 | 1.4067 | 0.5588 | 1.9473 | 0.9405 | 0.9013 |

## +2 tick rank
| Rank | Params | Total PnL | PF | Sharpe | p_edge | PF 95% low |
|---:|---|---:|---:|---:|---:|---:|
| 1 | 60/200/2.0 | 10381.86 | 1.5871 | 0.7720 | 0.9765 | 1.0098 |
| 2 | 60/200/1.8 | 9213.27 | 1.4732 | 0.6578 | 0.9670 | 0.9758 |
| 3 | 55/190/2.0 | 7570.26 | 1.4067 | 0.5588 | 0.9405 | 0.9013 |


## Verdict
60/200/2.0 remains top under +0/+1/+2 tick stress by total PnL/PF, but this does not change the PR #814 statistical-superiority failure or runtime-promotion block.

## Boundary
This is a cost robustness read, not statistical certification. Runtime promotion eligibility remains `NO`; any strategy parameter change requires a separate `[safety-review]` PR and explicit approval.

## Machine-readable artifact
- Repo: `engine/data/gate_v2_verdicts/MES_DEEP_TOP3_COST_SENSITIVITY_2026-09-12.json`
- Vault: `C:\Users\mattm\master-jarvis\second-brain\reports\MES_DEEP_TOP3_COST_SENSITIVITY_2026-09-12.json`
