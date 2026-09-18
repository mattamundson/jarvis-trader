# MES VIX-percentile-tier block — preregistered candidate verdict (2026-09-18)

Candidate: `MES_sma_trend_vix_pctile_blockCrisis_v1` (queue priority 4, state was `ready_to_backtest`)
Runner: `engine/backtest/run_mes_trend_vix_pctile_rank1.py` (unmodified, `origin/master` `9e4fd536`)
Verdict artifact: `engine/data/gate_v2_verdicts/MES_trend_vix_pctile_rank1.json`
Data: certified deep cache `MES_2019-05-05_2026-08-26_1h.csv` — 43,010 rows, span 7.307y,
`sha256 e26631c012b128284e61526dad78e7d39a3c180634dad7398a7dd8cc225f83fe` (meets the >=5y deep-data
standard; the ~2.16y cache that the repo worktree would otherwise select does not).

## Result: preregistered hypothesis FALSIFIED — do not promote, do not route

The server-side fixed-params sweep over the runner's 4-combo grid on the full deep dataset:

| blocked tiers | PF | trades |
|---|---|---|
| `[]` (no block — rank11 baseline) | **1.6478** | 122 |
| `["Crisis"]` (preregistered) | 1.4936 | 112 |
| `["Crisis","HighVol"]` | 1.4793 | 89 |
| `["HighVol"]` | 1.6659 | 99 |

The preregistered config (`vix_regime_block=["Crisis"]`) is **not** the champion: suppressing entries
while VIX sits in the Crisis tier *costs* PF versus blocking nothing (−0.1542 PF, −10 trades). The
adaptive-gate premise ("concentrates the trend edge") does not hold on this data. Per the frozen
activation protocol, the champion's blocked-tier set differs from `["Crisis"]`, so these params are
**not** mutated and no `forward_testing` flip is made.

The runner's nominal `verdict = PASS / passed_via = alt` applies to the champion (block = none, i.e.
the rank11 baseline reproduction), **not** to the preregistered Crisis variant — and even that reading
does not survive honest multiple-testing deflation:

| metric | value | bar | reading |
|---|---|---|---|
| `pf_ci_lower` | 2.2532 | >= 1.1 | pass |
| `p_edge` | 0.5926 | >= 0.95 (ALT) | fail |
| `mc_95th_dd` | 0.8902% | <= 4.0% | pass |
| `dsr` (grid basis, n_trials=4) | 0.9688 | >= 0.30 | pass |
| **`dsr_campaign`** (n_trials=210, 24 distinct artifacts) | **0.1937** | >= 0.30 | **fail** |
| `wfo_consistency` | MODERATE | MODERATE+ | pass |
| `fixed_params_min_pf` | 1.4793 | >= 1.2 | pass |
| OOS windows with trades | 54 / 82 | — | 47 of them fired exactly **1** trade |
| `sample_adequate_at_gate_floor` | false | true | fail |

Deflation is report-only in the runner (no threshold reads it), which is why the artifact still says
`PASS`; the honest reading of that PASS at the true campaign trial count is a fail.

## Independent reproduction

Re-ran the runner today in a clean worktree and got **bit-identical** statistical output:

- `pf_ci_lower` 2.2532, `p_edge` 0.5926, `mc_95th_dd` 0.008902, `dsr` 0.9688,
  `fixed_params_min_pf` 1.4793, `cost_survives_through` `catastrophic`,
  `champion_blocked_tiers` `[]` — all identical to the 2026-09-18T04:28:10Z artifact.
- Only the *deflation campaign count* moved (214 trials / 25 artifacts → **210 / 24**), because that
  number is derived from the committed verdict store, which itself changed when the cost-ledger fix
  (#879) landed. A derived lower bound moving with the store is expected, not drift.

Cost sweep on the champion (full dataset, 122 trades): optimistic PF 1.7060, realistic 1.6478,
pessimistic 1.6024, catastrophic 1.5077 — survives every tier. Cost was never the binding
constraint here; the sample and the multiple-testing correction are.

## Consequence

`MES_sma_trend_vix_pctile_blockCrisis_v1` moves to queue state `rejected`. It does not route orders
and never did. Reopening requires a *new* candidate id (a no-block variant is just the rank11
baseline, which independently fails `INSUFFICIENT_SAMPLE`) and a fresh honest gate-v2 PASS.

This is research evidence only: no routing, config, risk, kill-switch, or instrument-gate change.
