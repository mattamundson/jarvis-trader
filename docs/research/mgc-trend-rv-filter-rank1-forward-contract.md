# MGC trend RV-filter rank1 forward-evidence contract

Status: research-only data contract. This scaffold satisfies the queue's missing
contract step for `MGC_trend_rv_filter_rank1`, but it does not create fresh edge
evidence and does not authorize any paper/live routing.

No live trading config, paper trading config, risk limits, kill-switch state,
broker routing, API keys, `.env` files, PM2, active instrument gates, scheduled
tasks, or order behavior are changed.

## Candidate locked by the registry

- Candidate id: `MGC_trend_rv_filter_rank1`
- Symbol: `MGC`
- Family: `trend_rv_filter`
- Locked params: `fast=50`, `slow=120`, `atr_trail_mult=2.0`,
  `min_rv_annualized=9.0`
- Registry file: `engine/backtest/candidate_registry.json`
- Registry SHA256 at scaffold time:
  `00d8ac6760df5e7e0657cc2be70a1f761727a1a744fabfb890baa11881485389`
- Registry state: `forward_testing`, `deployed_live=false`

MGC remains halted. `deployed_live=false` is intentional: the runtime path must
not stamp live/paper orders to this mechanical candidate unless a future scoped
safety-review path explicitly changes runtime behavior.

## Historical artifact is not fresh permission

The only linked gate artifact in this scaffold is archived historical context:

| Artifact | Verdict | Key defect | Use |
|---|---:|---|---|
| `engine/data/gate_v2_verdicts/archive/MGC_trend_rv_filter_rank1_deep-2026-08-16.json` | PASS via ALT | core failed `p_edge=0.625 < 0.95`; archived, not fresh | historical context only |

Artifact SHA256:
`b88a7fa797597bd3d0eebd39ddbab44fc20eaf536ca5c8194658cc479d72c0e6`

This archived pass does not supersede MGC's halted status and does not clear the
queue's missing forward-evidence gates.

## Forward-evidence contract

Fresh evidence for this candidate must be zero-exposure and candidate-specific.
A future ledger/report must include, at minimum:

1. Exact candidate id and locked params on every row.
2. `zero_exposure=true`; no live or paper order route may be changed to collect
   the rows.
3. UTC entry/exit timestamps, side, quantity, entry/exit prices, gross P&L,
   fees, slippage, net P&L, source ledger, and strategy params.
4. A summary sidecar with ledger SHA256, first/last trade UTC, trade count,
   non-overlapping 30-day window count, profitable-window count, PF CI lower,
   p_edge, DSR deflated by the true campaign trial count, max drawdown, and cost
   model.
5. Minimum review sample before any status improvement: 60 candidate-tagged
   trades and 8 non-overlapping 30-day windows.

Symbol-only MGC context can be reported for liveness, but it cannot graduate
`MGC_trend_rv_filter_rank1`. Only `candidate_id` or exact-params attribution can
count as candidate evidence.

## Current queue effect

This PR converts the data-contract gap into a documented blocker. The candidate
is blocked until a fresh scoped backlog exists for a zero-exposure forward ledger
or fresh gate-v2 artifact. The next non-terminal queue item is therefore
`MES_sma_trend_vix_pctile_blockCrisis_v1`, subject to its own runner/cache
preconditions.

## Blocked without a separate `[safety-review]` PR

- Setting `deployed_live=true` for this candidate.
- Enabling MGC or changing active instrument gates.
- Changing JARVIS order routing, paper routing, broker credentials, PM2,
  `.env`, risk limits, or kill switches.
- Treating archived historical verdicts as fresh promotion evidence.
