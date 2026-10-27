# Morning Alpha Verification-of-Verification Design

**Status:** Approved scope for implementation  
**System:** JARVIS Morning Alpha  
**Purpose:** Validate the research machinery independently and adversarially before any real-market edge claim.

## Goal

Add a second-order falsification layer around Morning Alpha's L0-L14 research stack. The new layer must detect cases where the research framework appears internally consistent but is statistically misimplemented, contaminated by adversarial data defects, supported by placebo effects, or dependent on unrealistic fills.

No strategy rule, threshold, setup family, trigger, or promotion criterion is changed by this work.

## Principles

1. **Independent reference where possible.** Internal statistics must be cross-checked against SciPy/NumPy reference calculations or analytically tractable fixtures.
2. **Adversarial before optimistic.** Verification must deliberately inject known defects and prove they are detected.
3. **Placebos must fail.** Shuffled/time-shifted/randomized controls must not routinely produce evidence comparable to the real signal.
4. **Execution is a data-generating process.** Fill assumptions are tested through deterministic replay of quotes/bars, delays, partial fills, spread crossing, and gap-through events.
5. **Fail closed.** Missing reference data, missing quote evidence, ambiguous temporal ordering, or incomplete adversarial coverage cannot become a PASS.
6. **No promotion semantics.** A verification receipt can say `VERIFIED`, `FAILED`, or `INCOMPLETE`; it cannot authorize paper or live capital.

## V15 — Independent Statistical Conformance

### Scope

Cross-check internal statistical primitives against independent implementations.

Required checks:

- paired sign-flip permutation vs `scipy.stats.permutation_test` on exact small samples;
- date-cluster sign-flip permutation vs exhaustive cluster sign enumeration on small cluster fixtures;
- IID percentile bootstrap CI vs `scipy.stats.bootstrap(..., method="percentile")` within pre-registered Monte Carlo tolerance;
- cluster bootstrap on equal-sized clusters vs independent SciPy resampling of cluster indices;
- break-even transaction cost vs direct root/closed-form recomputation;
- deterministic seed repeatability;
- numerical behavior on zero variance, ties, negative edge, and highly skewed samples.

Conformance results persist:

- internal statistic;
- reference statistic;
- absolute/relative difference;
- tolerance;
- library versions;
- seed/resample count;
- fixture hash;
- status.

A disagreement beyond tolerance is fatal to the affected validation method.

## V16 — Adversarial Red-Team Validation

A deterministic red-team battery mutates otherwise-valid research artifacts and asserts that the correct gate fails.

Mandatory mutations:

1. append future price bars after decision time;
2. move `available_at` past the decision timestamp;
3. substitute today's survivor universe for PIT membership;
4. inject a future listing date;
5. expire historical sector membership before the decision timestamp;
6. shift SPY/sector benchmark endpoint by one session;
7. duplicate candidate identity;
8. change manifest hash after candidate construction;
9. tamper persisted candidate artifact bytes;
10. tamper membership-rejection bytes;
11. overlap OOS identities with development identities;
12. change locked strategy/parameter fingerprint after OOS sealing.

Every case records expected detector, actual detector, and whether the mutation was caught. A missed mutation is a hard verification failure.

## V17 — Negative-Control / Placebo Battery

Placebo methods preserve major marginal properties while destroying the hypothesized causal alignment.

Required placebo families:

- within-date candidate/control reassignment;
- date-block rotation of strategy outcomes;
- trading-date label shuffle preserving same-day cluster sizes;
- random eligible-universe control;
- same-sector random control;
- deterministic signal-date shift by ±N trading sessions where valid;
- irrelevant-feature pseudo-strategy with no access to future returns.

For each placebo family, persist the distribution of mean edge and the real-strategy percentile relative to the placebo distribution.

A strong result is suspicious if placebos routinely achieve similar or better evidence. Placebo results are diagnostic and do not independently promote or reject a strategy; they can, however, invalidate a research campaign when contamination is indicated.

## V18 — Microstructure / Execution Replay

### Data model

`ExecutionQuote`:
- timestamp;
- bid / ask;
- bid_size / ask_size;
- optional last trade;
- source lineage.

`ExecutionIntent`:
- side;
- quantity;
- trigger timestamp;
- trigger/reference price;
- stop price;
- maximum delay;
- maximum participation fraction;
- strategy/candidate identity.

### Deterministic replay rules

1. first eligible quote must be at or after trigger timestamp;
2. buy fills cross the ask; sell fills cross the bid;
3. delayed scenarios use 5s / 30s / 60s / 300s clocks;
4. fill quantity is capped by declared displayed-size participation;
5. unfilled quantity remains explicit and may expire rather than receiving a fantasy fill;
6. stop gap-through fills at the first executable market price, not the stop level;
7. spread, commissions, slippage/impact, and partial fills are all preserved separately;
8. missing quote evidence returns `UNVERIFIED_EXECUTION`, not zero cost.

Replay produces realized entry, fill ratio, implementation shortfall, realized R, and comparison with theoretical R.

## V19 — Verification Receipt and Reproducibility

Every V15-V18 run emits an immutable receipt containing:

- code commit;
- validation spec version;
- Python/SciPy/NumPy/statsmodels versions;
- data manifest hash;
- candidate population hash;
- trial-ledger hash;
- seeds;
- test fixture/artifact hashes;
- component statuses;
- overall status.

Overall status rules:

- `VERIFIED`: every declared component completed and passed;
- `FAILED`: at least one completed component failed;
- `INCOMPLETE`: required evidence or dependency unavailable.

`VERIFIED` means only that the verification machinery passed its own checks. It is not a trading-edge or promotion verdict.

## Testing Strategy

Golden fixtures must include:

1. correct positive sample whose internal/reference statistics agree;
2. negative edge sample;
3. tied/zero-variance sample;
4. heavily clustered same-day sample;
5. each adversarial corruption listed above;
6. placebo-null sample where real and placebo are indistinguishable;
7. contaminated sample where placebo evidence exposes leakage;
8. execution case with full fill;
9. partial-fill case;
10. delayed adverse-fill case;
11. gap-through-stop case;
12. missing-quote case that fails closed.

## Definition of Done

- All V15 reference checks are within pre-registered tolerances.
- All mandatory V16 corruptions are caught by their intended gates.
- V17 placebo distributions are deterministic and preserve declared marginal/cluster properties.
- V18 execution replay never assumes favorable fills from missing evidence.
- V19 receipts are deterministic and tamper-evident.
- Existing L0-L14 tests remain green.
- No strategy logic or promotion thresholds change.
- Real edge remains `UNVERIFIED` until certified PIT data executes the complete campaign.
