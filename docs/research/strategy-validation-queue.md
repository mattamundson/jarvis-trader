# Strategy validation queue

Wave 33 moves the completed repo-consolidation work into an execution queue for research validation.

This is not a routing change. It is a read-only queue that says what evidence must be gathered before any strategy can move forward.

## Why this exists

The repo estate has already been mined. The next bottleneck is not finding more ideas; it is preventing unvalidated ideas from leaking into paper/live routing.

The queue makes three things explicit:

1. what the next research action is;
2. what blocks promotion;
3. which gates are still missing.

## Source artifact

- Queue JSON: `engine/research/strategy_validation_queue.json`
- Helper: `engine/research/strategy_validation_queue.py`
- Tests: `engine/tests/test_strategy_validation_queue.py`

## Promotion gates

Every item must track the same gates:

1. hypothesis
2. data contract
3. backtest
4. fees/slippage
5. walk-forward
6. parameter stability
7. regime split
8. Monte Carlo / path risk
9. paper shadow
10. human approval

A candidate cannot become `promotion_candidate` unless all gates are true. A queue item still cannot route orders; live/paper routing remains governed by existing JARVIS runtime controls and any future Amo-approved safety-review change.

## Current recommendation

`MGC_trend_rv_filter_rank1` has a research-only forward-evidence data-contract scaffold at `engine/research/reference_evidence/mgc_trend_rv_filter_rank1_forward_contract.json`, but it remains blocked: MGC is halted, no fresh scoped runner/backlog exists, and no candidate-tagged zero-exposure forward ledger exists. The archived historical verdict is context only, not promotion evidence.

`MES_sma_trend_vix_pctile_blockCrisis_v1` is now terminal in this queue. PR #863 produced the preregistered deep-cache evidence and economics audit: the run's champion was `blocked_tiers=[]`, not the frozen `["Crisis"]` hypothesis; the Crisis block degraded PF/CAGR/honest Sharpe; DSR falls below the ALT floor at campaign-level trial counts; and p_edge is dominated by single-trade infinite-PF windows. Do not mutate this frozen candidate. Any follow-on must be a separate metric-repair PR or a newly registered no-gate candidate.

There are no non-terminal actionable items in the committed queue. A loop that reads this state should write a final status report and disable `Jarvis-Strategy-Validation-Loop` by readback rather than restarting repo-mining.

## Loop behavior

A validation loop should do one bounded step per run:

1. load `engine/research/strategy_validation_queue.json`;
2. select the highest-priority non-terminal item;
3. perform only the next missing evidence step;
4. write artifacts and tests;
5. open a small PR if evidence changed;
6. stop if no item is actionable.

Agentic loops must respect Amo's standing cadence: no more frequently than every 6 hours unless explicitly overridden.
