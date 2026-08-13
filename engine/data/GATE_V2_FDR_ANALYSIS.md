# Gate v2 Threshold Validation — Realized FDR Analysis

> Generated: 2026-05-23  
> Task: P3-8 — Re-validate gate v2 thresholds (realized FDR from trial multiplicity)  
> Analyzer: `engine/backtest/deflated_sharpe.py` + `optimization_log.jsonl`

---

## Summary

Both active PASS strategies (MES trend rank11, MGC trend rank4) fail the **CORE** gate via
`p_edge` and pass via the **ALT** path. This is expected and correct. The FDR analysis
confirms:

1. **DSR computation is correct** — champion Sharpe ~5.0 clears the selection-bias threshold
   even at 94 optimization trials.
2. **p_edge = 0.95 is mathematically correct** but requires ≥15 OOS windows to be
   statistically meaningful. With 4–8 windows, the ALT path is the operationally appropriate
   gate.
3. **ALT path criteria are jointly sufficient** — DSR ≥ 0.30 + WFO STRONG/MODERATE +
   fixed_params_min_pf ≥ 1.20 + cost_survives catastrophic + mc_dd ≤ 4% is a more demanding
   battery than the single CORE p_edge = 0.95 criterion alone.
4. **One latent gap**: n_trials in DSR computation is `n_combos_with_trades` from the gate v2
   grid (3–8), not the full optimization trial count (94 for MES). This doesn't affect current
   verdicts (Sharpe too high) but should be fixed for future lower-Sharpe strategies.

**Recommendation: No immediate threshold changes.** Add optimization trial count to DSR
computation (see §4 below).

---

## 1. Current Gate v2 Thresholds

| Criterion | CORE threshold | ALT threshold | MES rank11 | MGC rank4 |
|-----------|---------------|--------------|-----------|----------|
| `pf_ci_lower` | ≥ 1.10 | — | 2.50 ✅ | 2.60 ✅ |
| `p_edge` | ≥ 0.95 | not required | 0.75 ❌ | 0.68 ❌ |
| `mc_95th_dd_pct` | ≤ 5% | ≤ 4% | 0.81% ✅✅ | 1.24% ✅✅ |
| `dsr` | ≥ 0.10 | ≥ 0.30 | 1.0 ✅✅ | 1.0 ✅✅ |
| `wfo_consistency` | — | MODERATE or STRONG | STRONG ✅ | MODERATE ✅ |
| `fixed_params_min_pf` | — | ≥ 1.20 | 1.52 ✅ | 1.36 ✅ |
| `cost_survives_through` | — | ≥ realistic | catastrophic ✅ | catastrophic ✅ |

Both strategies pass via ALT. CORE fails only on `p_edge`.

---

## 2. DSR and Trial Multiplicity

### Optimization trials
94 MES parameter combinations were evaluated (`data/optimization_log.jsonl`).
Champion Sharpe: 4.985.

### DSR at various n_trials

| n_trials | E[max SR | null] | DSR | passes (≥0.10) |
|----------|----------------|-----|----------------|
| 3 (gate v2 grid) | 0.853 | 1.000 | ✅ |
| 8 (gate v2 grid) | 1.459 | 1.000 | ✅ |
| 94 (full opt run) | 2.509 | 1.000 | ✅ |

**Finding:** DSR = 1.0 is correct at all realistic n_trials values. The champion Sharpe of 4.985
is far above the selection-bias threshold even after 94 trials.

### Gap: n_trials mismatch

The runner uses `n_trials = n_combos_with_trades` (the narrow gate v2 grid), not the full
optimization trial count. For the current strategies this doesn't matter (SR too high), but a
future strategy with SR = 1.5 and 94 optimization trials would compute DSR incorrectly:

| n_trials | E[max SR] | SR=1.5 DSR | passes |
|----------|-----------|-----------|--------|
| 8 (current) | 1.459 | 0.631 | ✅ |
| 94 (correct) | 2.509 | 0.000 | ❌ |

A strategy that barely passes on n_trials=8 could fail on n_trials=94. This is the latent
gap — the DSR gate is under-penalizing for optimization-phase selection bias.

**Fix (see §4):** Read `n_optimization_trials` from `optimization_log.jsonl` and pass
`max(n_combos_with_trades, n_optimization_trials)` to `deflated_sharpe_ratio()`.

---

## 3. p_edge = 0.95 — Binomial FDR Analysis

`p_edge` = fraction of WFO OOS windows with PF > 1.0. Under the null (no edge, 50% win rate):

| OOS windows | P(p_edge ≥ 0.75 | luck) | P(p_edge ≥ 0.80 | luck) | P(p_edge ≥ 0.95 | luck) |
|-------------|---------------------|---------------------|---------------------|
| 4 | 31.25% | 6.25% | 6.25% |
| 6 | 10.94% | 10.94% | 1.56% |
| 8 | 14.45% | 3.52% | 0.39% |
| 12 | 7.30% | 1.93% | 0.02% |
| 16 | 3.84% | 1.06% | ~0.00% |
| 20 | 2.07% | 0.59% | ~0.00% |

### Calibrated minimum window requirements for p_edge = 0.95

To have FPR ≤ 5% with p_edge = 0.95, you need ≥ 7 OOS windows.
To have FPR ≤ 5% with the observed p_edge values (0.75 for MES, 0.68 for MGC):

| n_windows | Min p_edge for FPR ≤ 5% |
|-----------|------------------------|
| 6 | 0.85 (requires 6/6) |
| 8 | 0.80 (requires 7/8) |
| 12 | 0.80 (requires 10/12) |
| 16 | 0.70 (requires 12/16) |
| 20 | 0.75 (requires 15/20) |

### Why MES and MGC legitimately fail p_edge = 0.95

Both strategies have 4–8 OOS windows. At these small window counts:
- p_edge = 0.75 over 4 windows has **31% false positive rate** — not a strong signal
- p_edge = 0.95 at 4 windows means 4/4 wins, which happens 6.25% of the time by chance

The CORE threshold of 0.95 is **mathematically correct** but practically unreachable for
strategies with fewer than 15 OOS windows. The ALT path correctly compensates with a battery
of 5 joint criteria.

### Recommendation: Add minimum window enforcement to CORE

```python
# Proposed addition to gate v2 CORE logic:
GATE_MIN_OOS_WINDOWS_FOR_P_EDGE: int = 15

core_passes = (
    pf_ci_lower >= GATE_PF_CI_LOWER
    and p_edge >= GATE_P_EDGE
    and len(oos_pfs) >= GATE_MIN_OOS_WINDOWS_FOR_P_EDGE  # NEW
    and mc_dd <= GATE_MC_DD_CORE
    and dsr >= GATE_DSR
)
```

This makes it explicit that `p_edge = 0.95` only applies when there are enough windows for
the binomial test to be meaningful. Strategies with < 15 windows always take the ALT path.

---

## 4. Recommended Code Changes

### 4a. Fix n_trials in DSR (latent gap — low urgency for current strategies)

In `run_mes_trend_rank11.py` and each runner:

```python
# Current
dsr_result = deflated_sharpe_ratio(sharpe=mean_sharpe, n_trials=n_grid_combos, n_obs=n_obs)

# Proposed: also account for optimization trial count
import json
from pathlib import Path
_OPT_LOG = Path(__file__).parent.parent / "data" / "optimization_log.jsonl"
try:
    opt_entries = [json.loads(l) for l in _OPT_LOG.read_text().splitlines() if l.strip()]
    n_opt_trials = sum(1 for e in opt_entries if e.get("symbol") == SYMBOL)
except Exception:
    n_opt_trials = 0
n_trials_total = max(n_grid_combos, n_opt_trials)
dsr_result = deflated_sharpe_ratio(sharpe=mean_sharpe, n_trials=n_trials_total, n_obs=n_obs)
```

### 4b. Add GATE_MIN_OOS_WINDOWS_FOR_P_EDGE constant (documentation improvement)

In `_gate_v2_helpers.py`, add after `GATE_P_EDGE`:

```python
# Minimum OOS windows required for p_edge = 0.95 to have FPR <= 5% (binomial).
# Strategies with fewer windows always route via ALT.
GATE_MIN_OOS_WINDOWS_FOR_P_EDGE: int = 15
```

---

## 5. Verdict: Current Thresholds Are Sound

No immediate threshold changes are required. The system is working as designed:

- **CORE** = gold standard path (requires statistically robust p_edge with sufficient windows)
- **ALT** = operationally achievable path (substitutes joint multi-criteria robustness)
- **DSR** = selection-bias correction (currently passes; latent gap is low-urgency)

Both active strategies meet a demanding battery of criteria via ALT. The ALT certification
is not a weaker gate — it's a parallel gate that trades one strict criterion (p_edge) for
four additional constraints (DSR floor, WFO consistency, param robustness, cost survival).

The latent n_trials gap in DSR should be tracked but doesn't affect any current PASS/FAIL
decision and can be addressed in the next full WFO rerun.

---

## 6. Addendum (2026-07-29, PRB-02): the latent gap DID materialize — MGC_trend_baseline

§4a's "low urgency" call was correct for the two strategies analyzed in this document
(MES rank11, MGC rank4, both Sharpe ~5.0). It was **not** re-checked against every later
verdict file. `MGC_trend_baseline.json` (`backtest/run_mgc_trend_mtf_rank1.py`, generated
2026-07-27, the file currently authorizing MGC's live-traded champion params
fast=50/slow=120/atr_trail_mult=2.0) hits exactly the gap this document flagged: it is a
**single fixed-params backtest** (`n_grid_combos = 1`, no grid search), so its DSR was
computed as if this were the only strategy ever tried.

The 2026-07-27 `jarvis-honest-data-drain` loop (`~/.claude/loops/jarvis-honest-data-drain/ledger.json`)
independently established the TRUE trial count for the full MES+MGC+MCL+MNQ+M2K honest-data
research campaign: **70 scripts attempted, 54 of which produced an actual gate-v2 PASS/FAIL
verdict** (the other 16 never computed a Sharpe/p-value, so they aren't valid selection-bias
candidates). That loop found the SAME defect in a different script
(`research_candidates/run_bottom_detector_sd088.py`) and, recomputing its DSR at n=54/70,
watched its nominal PASS (dsr=0.869307) collapse to ~0.

`engine/scripts/recompute_mgc_trend_baseline_dsr.py` (added in this PR) applies the identical,
already-validated methodology to `MGC_trend_baseline.json`: re-run the SAME deterministic
single-fixed-params WFO backtest against the SAME honest MGC 1h reference
(`MGC_2024-03-04_2026-07-24_1h.csv`, the verified continuous series from the honest-data-drain
loop), and read `trade_level_dsr()` off the SAME 31-trade OOS series at n_trials=1 (sanity
check), 54, and 70.

| n_trials | dsr | CORE (>=0.10) | ALT (>=0.30) |
|---|---|---|---|
| 1 (as recorded in MGC_trend_baseline.json) | 0.999375 | PASS | PASS |
| 54 (honest-data-drain verdict-producing count) | 0.000000 | FAIL | FAIL |
| 70 (honest-data-drain full attempted universe) | 0.000000 | FAIL | FAIL |

The n_trials=1 recomputation reproduced the recorded 0.999375 exactly (same trade count, same
data file) — confirming this is the same trade series, not a different backtest. At the
correct campaign trial count, MGC's champion-params DSR collapses the same way sd-088's did:
**the recorded PASS is a multiple-testing artifact, not a real edge.**

Full output: `engine/data/gate_v2_dsr_corrections/MGC_trend_baseline_dsr_correction.json`.

**Not done by this addendum or its script:** `engine/data/gate_v2_verdicts/MGC_trend_baseline.json`
itself is intentionally gitignored (`.gitignore`, "Engine-mutated runtime state" comment,
2026-06-06 incident: a `git checkout` reverted a live verdict file to a stale committed copy and
silently mis-authorized trading) — this PR does not and cannot flip that file's `verdict` field
via git. See PRB-02 in `~/.claude/loops/jarvis-prod-readiness/backlog.json` for the live-audit
finding and the PR description for what Amo needs to decide.
