# MES IB Ladder + Weekly VWAP Acceptance + SPX Basis — Executive Evidence Index

**Research date:** 2026-09-27

**Branch:** `research/mes-ib-vwap-basis-20260927`

**Scope:** paper-only, local-only, MES-only. No live engine, risk configuration, kill switch, broker, `.env`, routing, MCL, or MNQ operational path was changed.

## Verdicts

| Phase | Verdict | Decision |
|---|---|---|
| 1. MES initial-balance sequential ladder | **REJECT** | Do not promote the tested family. Locked OOS economics are negative and worse than the simple IB-break baseline. |
| 2. MES weekly-VWAP acceptance | **REJECT** | Retain none of the five features. No feature beats both the price-above-VWAP and unconditional probability baselines after 10-comparison Holm correction while also clearing the economic rule. |
| 3. SPX→ES/MES basis translator | **ACCEPT** | Pure research utility is validated. It is not integrated into any live or paper order path. |

## Source-data lineage

### Primary 5-minute evidence

- Path: `C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache/MES_2024-09-22_2026-05-29_5m_cont.csv`
- SHA-256: `516beb11568f3270e595035b1dada669654c6b337f87b81b35fc386dff092a12`
- Rows: **119,096**
- Actual span: `2024-09-22T22:00:00Z` → `2026-05-29T20:55:00Z`
- RTH rows/sessions: **33,213 / 433**
- Integrity: 0 duplicate timestamps, 0 NaNs, 0 OHLC invariant violations, 5-minute modal/median cadence.
- Complete causal sessions after minimum-session gates: **417**.
- The source is stitched and not back-adjusted. Roll transitions can affect overnight references and weekly VWAP; this is a limitation, not an ignored data property.

### Wider 15-minute sensitivity evidence

- Path: `C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache/MES_2024-09-22_2026-06-29_15m.csv`
- SHA-256: `0add75b184cacc87b78b43ec3febb3c9a4e5cc985d07fe1b84c1f8806f6e7427`
- Rows: **41,619**
- Complete causal sessions: **437**.
- Used only as a lower-resolution terminal-window sensitivity check.

### Rejected merge

The audit compared overlapping later 5-minute caches. They disagreed on **20,000–31,000 overlapping OHLC rows**, with median price offsets near 50 points in later vintages. The files were not spliced. The single internally consistent primary cache remained authoritative.

## Phase 1 — MES initial-balance ladder

### Frozen rules

- RTH: `08:30 <= bar start < 15:00`, America/Chicago.
- IB: `08:30 <= bar start < 09:30`.
- Completed IB is unavailable to every pre-09:30 row.
- Entry family:
  1. stop-entry at the IB boundary;
  2. first completed post-IB close beyond the boundary.
- Stop family:
  1. IB midpoint;
  2. opposite IB extreme.
- Exit family:
  1. directional overnight extreme when it lies beyond entry;
  2. 0.5× IB extension;
  3. 1.0× IB extension;
  4. price-ordered, equal-unit ladder.
- First bar crossing both IB extremes: excluded as ambiguous.
- Target and stop touched in the same bar: **stop first**.
- Remaining units: RTH-close exit.
- Costs per round-trip contract:
  - fees/commission: **$1.42**;
  - baseline slippage: **1 tick per side = $2.50**;
  - stress: 2 and 3 ticks per side.

### Trial accounting

- Historical measured MES campaign lower bound: **210 trials** from 24 distinct content-hashed verdict artifacts.
- Current frozen family: `2 entry × 2 stop × 4 target = 16`.
- Empirical DSR deflation input: **226 trials**.
- Limitation: 226 is a measured lower bound, not unknowable exact truth; unlogged experiments can only make the honest deflation stricter.

### Descriptive ladder frequencies

- Complete sessions: **417**
- Sessions with an IB break: **409 / 417 = 98.08%**
- First break: **220 long / 189 short**
- Eligible overnight-extreme target hit: **60.00%**
- 0.5× extension hit after break: **58.92%**
- 1.0× extension hit conditional on hitting 0.5×: **51.45%**

These are touch frequencies, not trading expectancy.

### IS selection and locked OOS

- IS/OOS sessions: **250 / 167**
- IS-selected rule: `stop_entry__opposite_ib__full_ib__slip1`
- Locked OOS trades: **162**
- Net P&L: **−$1,930.04**
- Profit factor: **0.811870**
- Expectancy: **−$11.913827/trade**
- CAGR from $10,000: **−27.649555%**
- Max drawdown: **24.690722%**
- Observed-frequency Sharpe: **−1.330078**
- Campaign-deflated empirical DSR: **0.000000** at 226 trials
- Mean/median MFE: **20.371914 / 15.25 points**
- Mean/median MAE: **21.455247 / 18.125 points**
- Mean time-to-exit: **202.469136 minutes**
- Cost-ledger reconciliation residual: **$0.00**

### Benchmarks and robustness

- Simple first-IB-break benchmark expectancy: **−$9.228642/trade**
- Locked champion is therefore **$2.685185/trade worse** than the simple benchmark.
- +1 tick/side stress expectancy: **−$14.413827**
- +2 ticks/side stress expectancy: **−$16.913827**
- Disjoint halves:
  - H1 PF **0.644624**, expectancy **−$22.932346**
  - H2 PF **0.985589**, expectancy **−$0.895309**
- Expanding walk-forward: five of six windows had negative expectancy; the sole positive window did not rescue the family.
- Wider 15-minute sensitivity: PF **0.948701**, expectancy **−$3.092535**, CAGR **−7.699480%**, max DD **40.584737%**.

### Phase 1 verdict

**REJECT.** The high target-touch rates do not survive entry, stop, fees, slippage, chronology, or campaign deflation. Do not promote, retune around this failure, or modify live/paper parameters from this result.

## Phase 2 — Weekly-VWAP acceptance

### Causal feature definitions

- Weekly VWAP resets through the futures trade-date week key: Sunday 17:00 CT begins Monday’s week.
- Decisions occur at **10:30, 11:30, and 12:30 CT**.
- Each decision uses completed bars strictly before its timestamp.
- Features tested separately:
  1. **Time:** at least 5/6 latest closes above developing weekly VWAP and final 3 consecutive above.
  2. **Volume:** at least 60% of last-12-bar volume on bars whose typical price exceeds contemporaneous weekly VWAP, with decision price above VWAP.
  3. **Developing VPOC:** elapsed RTH bar volume distributed uniformly over crossed 0.25-point bins; POC above VWAP.
  4. **Developing TPO POC:** completed 30-minute periods only; TPO POC above VWAP.
  5. **CLV-delta proxy:** last-12-bar `close-location-value × volume` positive and price above VWAP. This is **not true bid/ask cumulative delta**.

### Outcomes

- Continuation: next RTH close > signal-session close.
- Failure: next close <= signal close and next low < signal-session low.
- Rotation: next close <= signal close and next low >= signal-session low.
- Trailing-only probabilities use symmetric Dirichlet α=1 and sum to 1.0.
- Predictions: **1,068 per feature / 356 unique signal dates**.
- Max probability-sum error before serialization: **1.11×10⁻¹⁶**.

### Paired OOS results

| Feature | Model Brier | Price>VWAP Brier | Unconditional Brier | Paired diff vs price | 95% block CI | Holm p price / unconditional | Net expectancy vs price baseline | Retained |
|---|---:|---:|---:|---:|---|---|---|---|
| Time | 0.566435 | 0.567764 | **0.565365** | +0.001329 | [−0.000238, +0.003057] | 0.422919 / 1.000000 | $23.644378 vs $22.609472 | No |
| Volume | 0.566434 | 0.567764 | **0.565365** | +0.001330 | [+0.000255, +0.002753] | 0.081980 / 1.000000 | $23.165153 vs $22.609472 | No |
| Developing VPOC | 0.565976 | 0.567764 | **0.565365** | +0.001788 | [−0.003874, +0.007589] | 1.000000 / 1.000000 | $24.045481 vs $22.609472 | No |
| Developing TPO POC | 0.567545 | 0.567764 | **0.565365** | +0.000219 | [−0.002117, +0.002411] | 1.000000 / 1.000000 | $23.293203 vs $22.609472 | No |
| CLV-delta proxy | 0.566162 | 0.567764 | **0.565365** | +0.001602 | [−0.002399, +0.005873] | 1.000000 / 1.000000 | $14.771239 vs $22.609472 | No |

Economic pooling allows the **earliest accepted decision only**, maximum one MES round trip per session; no triple-counted overlapping positions remain.

### Phase 2 verdict

**REJECT.** Volume narrowly beat the weak price-above-VWAP baseline before multiplicity correction, but lost to the unconditional base rate and failed the 10-comparison Holm gate. Every other feature also failed. The defensible probability model remains the trailing unconditional base rate.

The continuous-contract roll caveat can create weekly-VWAP measurement noise. Because the study rejects every feature, it does not create a false promotion; any future acceptance test must use explicit contract-aligned or properly adjusted data.

## Phase 3 — SPX-to-ES/MES basis translator

### Contract

- Preserve original SPX strike, spot, valuation time, futures contract/expiry, selected basis, source, translated level, ages, clock skew, and roll state.
- Theoretical carry:

  `F = S × exp((r − q) × T)`

  `basis = F − S`

  `translated strike = original SPX strike + selected additive basis`

- Prefer observed basis only when SPX and ES timestamps are fresh and synchronized.
- Reject stale observed basis and fall back to theoretical carry.
- Fail closed when SPX spot is stale.
- Reject expired contracts.
- Flag the configurable roll window.
- ES and MES share the same index-price level; symbol metadata remains distinct.

### Validated cases

- Theoretical Loom case: SPX **7750** → ES **7808.50**, theoretical basis **58.54126443**.
- Fresh observed case: SPX **7750**, ES **7810** → observed basis **60.00**, translated **7810.00**.
- Ten-minute-stale observed basis: rejected; theoretical fallback selected.
- MES output: same **7810.00** price level as ES with distinct `MES` metadata.
- Six days to expiry: roll-window flag true.
- Original strike preserved in every result.

### Phase 3 verdict

**ACCEPT** as a pure, tested research utility. This verdict does not authorize runtime integration or any engine/risk/routing change.

The validation is functional: the Loom observed example plus deterministic staleness, skew, expiry, and roll cases. It is not an independent historical basis-forecast backtest.

## Verification evidence

- `py_compile`: all new source and test modules passed.
- Targeted pytest: **17 passed, 0 failed**; one unrelated `pandas_ta` deprecation warning.
- Ruff: **All checks passed** on all new modules/tests.
- `git diff --check`: passed.
- End-to-end harness: exit **0**.
- Independent artifact verifier: exit **0**, `all_verified=true`.
  - Phase 1 raw CSV count/net/PF and aggregate cost identity reproduced.
  - Phase 2 raw JSONL Brier, expectancy, earliest-one-per-date count, and probability sums reproduced.
  - Phase 3 carry arithmetic reproduced independently.
- Reviewer limitation: two delegated review attempts timed out without findings; a TypeSafe Jev review could not run because no provider credential was available. Neither unavailable reviewer is claimed as evidence.

## Reproduction

```bash
cd C:/Users/mattm/ThinkorSwim/wt-mes-ib-vwap-basis-20260927

env -u PYTHONPATH API_KEY='local-research-sandbox-dummy-not-a-credential' \
  C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/.venv/Scripts/python.exe \
  engine/backtest/research/run_mes_ib_vwap_basis.py \
  --out-dir .hermes/artifacts/mes_ib_vwap_basis_20260927

env -u PYTHONPATH API_KEY='local-research-sandbox-dummy-not-a-credential' \
  C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/.venv/Scripts/python.exe \
  engine/backtest/research/verify_mes_ib_vwap_artifacts.py \
  --out-dir .hermes/artifacts/mes_ib_vwap_basis_20260927
```

## Artifact map

- `docs/research/MES_IB_LADDER_20260927.md`
- `docs/research/MES_WEEKLY_VWAP_ACCEPTANCE_20260927.md`
- `docs/research/SPX_ES_BASIS_TRANSLATOR_20260927.md`
- `.hermes/artifacts/mes_ib_vwap_basis_20260927/manifest.json`
- `.hermes/artifacts/mes_ib_vwap_basis_20260927/data_provenance.json`
- `.hermes/artifacts/mes_ib_vwap_basis_20260927/phase1_mes_ib_ladder.json`
- `.hermes/artifacts/mes_ib_vwap_basis_20260927/phase1_is_trades.csv`
- `.hermes/artifacts/mes_ib_vwap_basis_20260927/phase1_oos_trades_all_costs.csv`
- `.hermes/artifacts/mes_ib_vwap_basis_20260927/phase1_ladder_events.csv`
- `.hermes/artifacts/mes_ib_vwap_basis_20260927/phase2_weekly_vwap_acceptance.json`
- `.hermes/artifacts/mes_ib_vwap_basis_20260927/phase2_acceptance_records.csv`
- `.hermes/artifacts/mes_ib_vwap_basis_20260927/phase2_walkforward_rows.jsonl`
- `.hermes/artifacts/mes_ib_vwap_basis_20260927/phase3_spx_es_basis.json`
- `.hermes/artifacts/mes_ib_vwap_basis_20260927/artifact_hashes.json`
