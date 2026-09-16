# JARVIS Morning Alpha — Validation L6-L14 Design

**Date:** 2026-09-15  
**Status:** Approved architecture  
**Scope:** Validation layers after population integrity (L0-L2) and statistical/concentration/execution validation (L3-L5).

## 1. Objective

Increase confidence that any observed Morning Alpha edge is persistent, transferable, execution-survivable, and not an artifact of model selection, data snooping, regime concentration, one vendor, or repeated backtest experimentation.

No validation stack can make a market edge literally “soundproof.” The objective is to make false discovery progressively harder and to preserve enough evidence to detect degradation after paper deployment.

## 2. Evidence Hierarchy

```text
L0  Dataset integrity
L1  PIT / temporal integrity
L2  Population integrity
L3  Statistical uncertainty
L4  Concentration robustness
L5  Execution survivability
L6  Locked chronological OOS
L7  Purged rolling walk-forward
L8  Regime / structural robustness
L9  Cluster-aware Monte Carlo
L10 Canonical Gate-v2
L11 Immutable paper-forward validation
L12 Multiple-testing / data-snooping defenses
L13 Independent replication / shadow execution
L14 Continuous edge-decay monitoring
```

`EVIDENCE_COMPLETE`, Gate-v2 PASS, PAPER, FORWARD_VALIDATED, and LIVE_ELIGIBLE remain distinct states.

## 3. L6 — Locked Chronological OOS

### 3.1 Rule

The final OOS interval is declared before its outcomes are inspected for parameter selection. Development and validation code may not access OOS metrics through the tuning interface.

### 3.2 Required evidence

Persist an immutable lock containing:

- campaign ID;
- strategy version;
- parameter/config hash;
- trigger/exit versions;
- data-manifest hash;
- candidate-population hash;
- trial-ledger hash/count;
- development interval;
- validation interval;
- final OOS interval;
- purge/embargo policy;
- code commit;
- lock timestamp and lock hash.

Any strategy/config change after the lock creates a new research trial and invalidates reuse of the previous OOS block as “unseen.”

### 3.3 Failure conditions

- overlapping intervals;
- OOS accessed by selection/tuning code;
- parameters differ from lock;
- population/data identity differs from lock;
- forward labels cross split boundaries without purging.

## 4. L7 — Purged Rolling Walk-Forward

Generate chronological train/test folds. Selection receives only train observations. Evaluation receives only test observations plus the frozen selection output.

Each fold persists:

- train/test boundaries;
- purged train-tail observations;
- embargoed test-head observations;
- selected parameter/config identity;
- train metrics;
- test metrics;
- trade count;
- fold evidence hash.

Required summary includes median test expectancy, fraction of positive folds, worst fold, parameter stability, IS→OOS degradation, and aggregate test R without double-counting overlapping test observations.

## 5. L8 — Regime and Structural Robustness

Segment OOS/WFO evidence by pre-registered dimensions including:

- SPY long/intermediate trend;
- VIX bucket;
- breadth state;
- rates direction;
- QQQ/IWM leadership;
- sector;
- symbol;
- year / month;
- volatility bucket;
- scheduled-event state where certified data exists.

Report minimum sample sizes, expectancy/CI by bucket, worst bucket, strongest bucket, and leave-one-bucket-out expectancy. A single regime, sector, year, or symbol must not explain nearly all aggregate performance without being explicitly flagged as concentration fragility.

## 6. L9 — Cluster-Aware Monte Carlo

Monte Carlo resampling uses trading-date clusters or approved blocks rather than IID trades as the primary path generator.

Report distributions for:

- cumulative R;
- maximum drawdown in R;
- maximum losing streak;
- time under water / recovery where measurable;
- 50th/90th/95th/99th percentile drawdown;
- probability of crossing configured capital-loss thresholds;
- probability of negative terminal R.

Random seed, cluster definition, number of paths, and input-evidence hash are persisted.

## 7. L10 — Canonical Gate-v2

Morning Alpha must continue to call `backtest.wfo_lifecycle.compute_gate_v2`; no duplicate Gate-v2 formulas are permitted.

Gate-v2 is invoked only after L6-L9 evidence requirements are satisfied. A Gate-v2 PASS means research certification, not live authorization.

## 8. L11 — Immutable Paper-Forward Validation

Signals are timestamped and persisted before outcomes are known. Paper records preserve:

- strategy/version;
- exact pre-outcome features;
- trigger/entry/stop/targets;
- expected transaction cost/slippage;
- actual paper fill/slippage;
- market/sector/regime context;
- immutable signal hash;
- later outcome audit as a separate record.

Compare historical expectations with paper-forward expectancy, trigger rate, fill rate, slippage, MFE/MAE, and regime-conditioned behavior. Paper-forward evidence never rewrites the backtest.

## 9. L12 — Multiple-Testing and Data-Snooping Defenses

The trial ledger is the authoritative inventory of tried hypotheses. The following analyses are additive falsification layers, not alternatives to OOS/WFO:

### 9.1 DSR

Retain existing Deflated Sharpe / Gate-v2 trial-count discipline.

### 9.2 PBO / CSCV

Estimate the probability that the in-sample-selected configuration underperforms out of sample using combinatorially symmetric cross-validation when the number of variants and observations supports the procedure.

Persist partition definition, selected variant per split, OOS rank/logit, degradation statistics, and PBO estimate.

### 9.3 White Reality-Check style bootstrap

Evaluate the best observed model against a benchmark while resampling time blocks/clusters so the null accounts for searching across multiple alternatives.

### 9.4 Hansen SPA-style test

Provide a more powerful data-snooping test that reduces sensitivity to clearly poor/irrelevant alternatives. Method/version/bootstrap block definition are persisted.

### 9.5 Stepwise family-wise-error control

For families of related hypotheses, support a Romano-Wolf-style stepdown/bootstrap procedure or another explicitly versioned strong-FWER procedure. Report adjusted p-values; never substitute raw p-values when multiplicity correction was pre-registered.

### 9.6 Model Confidence Set sensitivity

Where loss-series structure is appropriate, optionally report an MCS-style surviving set of statistically indistinguishable candidate models. MCS membership does not select a production strategy by itself.

## 10. L13 — Independent Replication and Shadow Execution

### 10.1 Second-source replay

Replay the frozen strategy on an independently sourced/normalized dataset when available. Compare:

- candidate identity overlap;
- feature deltas;
- trigger deltas;
- outcome deltas;
- expectancy / CI;
- sector/regime distributions;
- missingness and corporate-action differences.

Provider lineage must be independent enough that the replay can expose vendor-specific artifacts.

### 10.2 Shadow execution

During paper-forward operation, an independent shadow pipeline recomputes signals from a separately normalized feed without influencing the primary decision. Divergences are journaled before outcomes.

## 11. L14 — Continuous Edge-Decay Monitoring

For Gate-v2-passed paper strategies, continuously monitor pre-registered rolling statistics:

- rolling expectancy R;
- profit factor;
- selection/timing attribution;
- MFE/MAE;
- trigger/fill rates;
- realized slippage vs modeled slippage;
- regime-adjusted expectancy;
- concentration changes.

States:

```text
NORMAL
WATCH
DEGRADED
HALTED
```

Transitions use versioned statistical rules, minimum sample sizes, and cooldown/recovery requirements. One losing trade cannot trigger a state change. A HALTED strategy requires explicit revalidation/new evidence before resumption.

## 12. Adversarial Validation Enhancements

In addition to L6-L14, preserve a red-team suite:

- label/time-shift placebo;
- shuffled candidate dates;
- random eligible controls;
- deliberate future-row injection that must not change prior decisions;
- drop/reorder input rows;
- missing-data and stale-data stress;
- symbol-change/split/delisting fixtures;
- alternate transaction-cost assumptions;
- alternate bootstrap block lengths;
- remove strongest symbol/sector/year/regime;
- re-run from a clean environment and compare artifact hashes.

## 13. Reproducibility Contract

Every validation artifact must be bound to:

- code commit;
- environment/dependency identity where available;
- strategy/config version;
- data-manifest hash;
- candidate-population hash;
- split/fold registry hash;
- trial-ledger hash/count;
- deterministic random seeds;
- validation-spec version;
- output artifact SHA-256.

Unchanged inputs must reproduce the same deterministic intermediate identities. Stochastic summaries must be reproducible under the stored seeds.

## 14. Promotion Semantics

```text
L0-L5 evidence complete
    ↓
L6 locked OOS positive under pre-registered criteria
    ↓
L7 acceptable purged WFO
    ↓
L8 structural/regime robustness acceptable
    ↓
L9 Monte Carlo risk acceptable
    ↓
L10 canonical Gate-v2 PASS
    ↓
L11 PAPER
    ↓
L12 multiplicity/data-snooping evidence reviewed
    ↓
L13 independent replication/shadow evidence reviewed
    ↓
FORWARD_VALIDATED
```

Live eligibility, if ever considered, remains a separate future decision with independent risk/safety approval.

## 15. Definition of Done

This validation architecture is implemented when:

- OOS is cryptographically/configurationally locked before final evaluation;
- WFO folds enforce purge/embargo and train/test API separation;
- regime/structural fragility is explicitly reported;
- Monte Carlo is date-cluster/block aware;
- Gate-v2 remains canonical and cannot be invoked early;
- paper-forward signals are immutable pre-outcome records;
- PBO/CSCV and at least one bootstrap data-snooping test are available when sample structure permits;
- multiplicity-adjusted evidence is supported for strategy families;
- independent-provider replay/shadow comparison is supported;
- edge-decay monitoring can halt degraded paper strategies;
- all failures/insufficient-data states are preserved rather than tuned away.
