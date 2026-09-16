# JARVIS Morning Alpha Research Protocol

## Principle

Morning Alpha is falsifiable research, not a narrative stock picker. A strategy version is promoted only when evidence survives chronological validation and realistic implementation costs.

## Pre-registration

Before final OOS evaluation, freeze:

- strategy family/version;
- universe and liquidity rules;
- features and thresholds;
- trigger candidates;
- stop/target construction;
- holding horizon;
- cost/slippage assumptions;
- regime filters; and
- promotion thresholds.

Any material rule change creates a new strategy version and a new trial. Failed versions remain in the registry.

## Independent family order

1. `relative_strength_breakout@1.0.0`
2. `sector_rotation@1.0.0`
3. `post_earnings_drift@1.0.0`
4. `momentum_breakout@1.0.0`
5. `pullback_continuation@1.0.0`
6. `gap_continuation@1.0.0`

Do not optimize a blended composite until independent-family evidence is understood.

## Point-in-time correctness

Every decision uses only information with timestamps at or before `as_of`. Universe membership, prices, earnings/news timestamps, sector mappings, and macro/event flags must all be point-in-time safe. A future-data violation invalidates the run.

## Validation sequence

1. Development/in-sample research.
2. Chronological out-of-sample validation.
3. Rolling walk-forward optimization/validation where applicable.
4. Fixed-parameter robustness sweep.
5. Cost/slippage stress.
6. Monte Carlo drawdown/streak analysis.
7. Regime segmentation.
8. Canonical Gate-v2.
9. Paper-forward observation.
10. Separate forward-validation/live-eligibility decision.

## Trial-count / DSR discipline

Deflated Sharpe trial counts must include the actual hypothesis/parameter search campaign, not only the winning grid row. Re-running modified hypotheses increases the effective trial count. Do not reset trial history to obtain a better DSR.

## Costs

At minimum evaluate 0, 2, 5, 10, and 20 bps round-trip sensitivity plus explicit slippage shocks. An edge that vanishes under modest costs is not production-grade.

## Trigger laboratory

Compare exactly versioned variants:

- market open;
- prior-day high/low;
- premarket high/low;
- ORB 5m;
- ORB 15m;
- ORB 30m;
- breakout + retest; and
- VWAP reclaim/rejection.

Do not choose the in-sample maximum without OOS confirmation. Track filtered losers and filtered winners so confirmation thresholds are evaluated as trade-offs, not anecdotes.

## Outcome audit

MFE/MAE begins at actual entry time. If an OHLC bar contains both stop and target with unknown ordering, classify `UNVERIFIED` unless higher-resolution data resolves the sequence. Never assume favorable ordering.

## Promotion lifecycle

```text
IDEA -> BACKTESTED -> WFO_VALIDATED -> GATE_V2_PASSED -> PAPER
     -> FORWARD_VALIDATED -> LIVE_ELIGIBLE
```

`DEGRADED` and `RETIRED` are valid terminal/monitoring states. Gate-v2 PASS alone never authorizes live execution.

## Minimum sample

Normal setup families require at least 200 historical trades before Gate-v2. A sparse-strategy exception must be explicitly approved under the repository's existing Gate-v2 sparse-strategy discipline and documented before evaluation.

## Reproducibility

Every research run should persist:

- code/strategy version;
- as-of range;
- provider/data lineage;
- universe definition;
- trigger version;
- costs/slippage;
- trial count;
- OOS/WFO windows;
- per-trade R series;
- Gate-v2 verdict; and
- failure reasons.

## Dataset certification before campaign execution

The pre-registered campaign must not start merely because bar files exist. `research_manifest.json` is the dataset evidence contract and must satisfy the campaign thresholds enforced by `inspect_research_files()`. Manifest v1.1 must be generated from immutable artifact receipts rather than hand-edited evidence flags. Each receipt binds an evidence file to its provider, relative path, SHA-256, coverage metadata, and point-in-time assertion. Readiness recomputes hashes from disk before certification.

Frozen v1 minimums:

```text
min_daily_symbols     = 500
min_intraday_symbols  = 100
min_history_years     = 8
```

Required evidence flags:

```text
point_in_time_universe = true
delisted_symbols       = true
corporate_actions      = true
sector_history         = true
earnings_events        = true
macro_context           = true
source_lineage         = true
premarket_bars         = true
```

A failed readiness check is a research stop condition, not an invitation to relax requirements. Any future change to these minimums must be treated as a new campaign specification and documented before results are viewed.

## Relative Strength Sprint 1 controls

`relative_strength_breakout@1.0.0` is evaluated against matched point-in-time controls at the original decision timestamp:

1. deterministic random eligible-universe stock;
2. deterministic random same-sector stock;
3. the same stock entered at the next eligible regular-session open;
4. SPY over the same horizon; and
5. the corresponding sector ETF when it actually existed at the historical timestamp.

Random controls are seeded from immutable campaign/candidate identity. A missing control is recorded as unavailable; it is never substituted from a future universe or current survivor list.

## Edge attribution semantics

Sprint 1 decomposes strategy-minus-market performance using transparent counterfactual differences:

```text
sector increment    = sector return - market return
selection increment = same-stock next-open return - sector return
timing increment    = strategy return - same-stock next-open return
```

Explicit exit/filter adjustments may be added only when those counterfactual studies exist. A residual term reconciles the components exactly to the total strategy-minus-market increment. Negative selection/timing contributions are preserved; attribution never clips an unfavorable result.

## Ablation versioning

Initial diagnostic variants are:

- `FULL`;
- `FULL_MINUS_SECTOR_FILTER`;
- `FULL_MINUS_VOLUME_CONFIRMATION`;
- `FULL_MINUS_REGIME_FILTER`; and
- `FULL_MINUS_ENTRY_CONFIRMATION`.

Ablations are research variants, not silent strategy edits. If an ablation appears superior, it requires a new explicit strategy version and a new validation cycle before any promotion decision.

## Immutable trial ledger

Every attempted experiment is recorded with an identity derived from:

- campaign ID;
- strategy key;
- control version;
- trigger version;
- exit version;
- ablation kind;
- parameter fingerprint;
- cost assumption;
- data-manifest hash; and
- sample interval.

Result status, sample size and output artifacts are not part of the trial identity. Failed trials remain queryable and still count toward the multiple-testing burden used by DSR/Gate-v2.

## Parameter robustness rule

Research must prefer broad stable parameter plateaus to isolated in-sample maxima. Diagnostics track adjacent expectancy dispersion, maximum neighbor drop, positive-neighbor fraction and minimum sample size. The robustness layer does not emit a recommended parameter value.

A narrow spike surrounded by materially worse neighbors is treated as fragile evidence even if it has the highest in-sample return.

## Sprint 1 conclusion semantics

The Relative Strength research sprint may report `BLOCKED`, `INSUFFICIENT_DATA`, `FAIL`, or later evidence-ready validation states. The raw forward-return/control stage is never sufficient for PASS. Trigger, excursion, exit, cost, OOS, WFO, robustness, Monte Carlo/regime evidence and canonical Gate-v2 remain separate required stages before paper promotion.
