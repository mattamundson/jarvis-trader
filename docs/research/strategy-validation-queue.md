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

**No queue item is actionable.** The last non-terminal research item,
`MES_sma_trend_vix_pctile_blockCrisis_v1`, was resolved on 2026-09-18 and moved to `rejected`:

- Its preregistered config (`vix_regime_block=["Crisis"]`) is **not** the champion of the runner's
  4-combo grid. Blocking nothing won outright on the certified deep cache
  (`MES_2019-05-05_2026-08-26_1h.csv`, 43,010 rows, sha256 `e26631c0…`): PF 1.6478 / 122 trades for
  no block versus 1.4936 / 112 trades for `["Crisis"]`. The adaptive-percentile premise is falsified.
- The runner's nominal `PASS via alt` belongs to that no-block champion (a rank11 baseline
  reproduction), not to the frozen preregistered params — and it does not survive honest
  multiple-testing deflation: `dsr_campaign` **0.1937** on 210 campaign trials (24 distinct
  content-hashed artifacts) against the 0.30 ALT floor, with 47 of 82 OOS windows firing exactly one
  trade (`sample_adequate_at_gate_floor=false`).
- Frozen params were **not** mutated. The activation protocol requires a new id when the champion
  tier set differs from the preregistration, so reopening means a new candidate id plus a fresh
  honest gate-v2 PASS.

Evidence: `engine/data/gate_v2_verdicts/MES_trend_vix_pctile_rank1.json`;
write-up: `docs/research/mes-vix-pctile-blockcrisis-verdict-2026-09-18.md`.

Remaining items are terminal non-promotable: `MGC_trend_rv_filter_rank1` (blocked — MGC halted, no
deep MGC cache, no Databento credential), `MGC_trend_rank4` (halted), `MES_trend_rank11` and
`SPY_stc_trend_meta_rank1` (rejected), `repo_reference_patterns` (blocked reference material, never
alpha). With zero actionable items the validation loop stops here and writes its final status rather
than inventing work; it restarts only on a fresh scoped backlog (e.g. an MGC data-unblock or a newly
registered candidate id).

## Loop behavior

A validation loop should do one bounded step per run:

1. load `engine/research/strategy_validation_queue.json`;
2. select the highest-priority non-terminal item;
3. perform only the next missing evidence step;
4. write artifacts and tests;
5. open a small PR if evidence changed;
6. stop if no item is actionable.

Agentic loops must respect Amo's standing cadence: no more frequently than every 6 hours unless explicitly overridden.
