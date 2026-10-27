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
macro_context          = true
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


## Historical candidate population validation — Levels 0–2

No performance or edge statistic may be trusted until the historical candidate population passes Levels 0–2.

### Canonical decision clock

Every historical morning is reconstructed at exactly `09:00 America/New_York`. Inputs with availability or market-data timestamps after that instant are forbidden. Completed prior-session daily bars and premarket information through 09:00 ET are permitted; same-day RTH high/low/close/volume are not.

### Level 0 — dataset and run identity

Require certified research readiness, a 64-character data-manifest identity, timezone-aware decision timestamps, source lineage, deterministic candidate IDs, and a population artifact bound to code commit, split registry, population hash, universe hash, and decision-clock contract.

### Level 1 — temporal / PIT integrity

Historical listing/delisting and sector-effective intervals are audited independently from candidate features. A source security row that is not part of the true PIT universe is preserved in the membership-rejection ledger rather than silently disappearing. Future market-data timestamps, future listing/classification data, or expired membership supplied as if current are fatal validation evidence.

Relative Strength feature windows must use aligned stock/SPY/sector endpoints. Missing benchmark endpoints are rejected; they are never forward-filled invisibly. Appending future rows must not alter prior candidate observations or population hashes.

### Level 2 — population integrity

Candidate identities must be unique, candidate/rejection counts must reconcile, and source records must equal PIT-universe records plus membership-rejection records. Re-running unchanged inputs must reproduce candidate IDs, feature hashes, universe hash, and population hash exactly.

The persisted population contains two independently hashed artifacts:

- `candidates.jsonl`;
- `membership_rejections.jsonl`.

Tampering with either invalidates the population artifact.

### Purge and embargo semantics

The default maximum forward label horizon is 20 trading sessions. Purging removes the **tail** of any split whose forward labels could cross into the next split. Embargo is a distinct **head** exclusion applied after a split boundary. The final split is not tail-purged because no later holdout boundary exists.

Current defaults:

```text
purge_sessions   = 20
embargo_sessions = 0
```

These defaults are exposed by `python -m morning_alpha.cli research-split-plan --json`. Changing them after final OOS results are viewed constitutes a new research specification.

### Interpretation boundary

`POPULATION_VALIDATED` means the historical sample passed structural/data validation. It is **not** evidence of profitable edge and must never be reported as such.


## Statistical validation — Levels 3–5

After a candidate population passes structural Levels 0–2, Morning Alpha evaluates uncertainty, concentration, and execution survivability before OOS/Gate-v2 promotion work.

### Level 3 — statistical uncertainty

The primary estimand is matched edge: `strategy_return - control_return` for the same historical decision context. Date clustering is the primary dependence correction because same-day signals share market shocks. IID inference remains diagnostic only; sector clustering is a sensitivity view.

Default evidence floors are:

```text
min_observations       = 200
min_date_clusters       = 30
min_sector_clusters     = 3
bootstrap_resamples     = 10,000
permutation_resamples   = 10,000
confidence              = 95%
```

The primary randomization test flips all observations from a trading date together. A deterministic date-cluster placebo breaks matched candidate/control pairing while preserving the marginal control-return distribution and date-cluster membership counts. IID permutation/placebo results are diagnostic sensitivity checks only. Neither p-values nor confidence intervals are promotion rules.

### Level 4 — concentration robustness

Every evidence package must report whether apparent edge is concentrated in a small number of trades or groups. Required diagnostics include:

- top-1 / top-5 / top-10%-of-trades positive-contribution shares;
- expectancy after removing top positive trades;
- strongest symbol, sector, year, and regime;
- expectancy after removing each strongest group;
- top-5-symbol and top-10%-of-symbol removals;
- retained-edge ratios after each removal so concentration fragility is comparable across samples;
- positive-contribution HHI-style concentration for symbols, sectors, years, and regimes.

If removing a dominant group eliminates the sample, the post-removal mean is unavailable rather than zero.

### Level 5 — execution survivability

Execution analysis uses observation-specific historical coefficients; missing evidence is never silently treated as zero friction.

Frozen transaction-cost curve:

```text
0 / 2 / 5 / 10 / 20 bps
```

Frozen ATR-slippage fractions:

```text
0.00 / 0.02 / 0.05 / 0.10 ATR
```

Delay sensitivity scenarios:

```text
5s / 30s / 1m / 5m
```

The evidence package reports exact bps break-even, ATR-slippage break-even, delay curves, gap-through penalties when declared, and combined expectancy under the declared realistic cost/slippage/delay/gap scenario. Partial gap evidence is invalid rather than silently treated as zero friction.

### Evidence-status semantics

`EVIDENCE_COMPLETE` means the required analyses ran with sufficient structural sample size. It does **not** mean strategy PASS, edge confirmed, Gate-v2 PASS, or paper eligibility.

`INSUFFICIENT_DATA` is used when the sample or independent cluster structure is below the pre-registered floor. `INVALID` is used for internally inconsistent or incomplete declared execution/statistical evidence.

The report must always state:

> This statistical evidence package is not a strategy promotion verdict.

## Extended validation hierarchy: L6-L14

After L3-L5 evidence is complete, Morning Alpha does not treat statistical significance as final proof. The post-L5 validation sequence is:

1. **L6 Locked chronological OOS** — final OOS interval, parameter identity, data manifest, population hash, trial ledger and code commit are sealed before evaluation. Tuning code cannot consume final OOS metrics.
2. **L7 Purged rolling walk-forward** — train/test APIs are separated; train tails are purged and test heads embargoed for overlapping forward labels; overlapping OOS observations are not double counted.
3. **L8 Regime / structural robustness** — report worst/strongest buckets and leave-one-bucket-out expectancy for regime, sector, symbol, year and other pre-registered dimensions.
4. **L9 Cluster-aware Monte Carlo** — resample trading-date clusters/blocks rather than IID trades and report terminal-R, drawdown, losing-streak and threshold-crossing distributions.
5. **L10 Canonical Gate-v2** — invoke only through `backtest.wfo_lifecycle.compute_gate_v2`, and only after complete L6-L9 evidence with consistent identity.
6. **L11 Immutable paper-forward** — persist signals before outcomes and append outcomes separately. Historical expectations are compared to actual paper trigger/fill/slippage/MFE/MAE/R evidence without rewriting backtests.
7. **L12 Multiple-testing / data-snooping defenses** — retain DSR trial counts and add CSCV/PBO, block-bootstrap Reality-Check-style evidence, SPA-style sensitivity and multiplicity-adjusted family tests when sample structure supports them.
8. **L13 Independent replication / shadow execution** — replay on independently sourced data and journal primary-vs-shadow signal divergence before outcomes.
9. **L14 Continuous edge-decay monitoring** — versioned NORMAL/WATCH/DEGRADED/HALTED rules monitor rolling expectancy and execution drift. HALTED is sticky until explicit revalidation.

None of these states alone authorizes live execution. `EVIDENCE_COMPLETE`, Gate-v2 PASS, PAPER, FORWARD_VALIDATED and LIVE_ELIGIBLE remain distinct states.

### Multiple-testing method labeling

Backtest-overfitting and data-snooping procedures must retain explicit method/version labels. Approximate or adapted implementations must use labels such as `Reality-Check-style`, `SPA-style`, or `Romano-Wolf-style`; they must not be represented as canonical replications of the published procedures unless separately verified against reference implementations and test vectors.

### No “soundproof” claim

Market edges are non-stationary and cannot be proven permanent. The objective is progressive falsification: make false discovery, hidden dependence, implementation friction, vendor artifacts and edge decay increasingly difficult to overlook. A strategy can be halted or retired after promotion if forward evidence degrades.
