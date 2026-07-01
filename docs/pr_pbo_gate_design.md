# PR-based PBO Gate — Strategy Design Doc

**Status:** Implemented in `.github/workflows/funnel-quality-gate.yml` + `scripts/ci/check_pbo_gate.py`
**Target repo:** `mattamundson/jarvis-trader`
**PR branch:** `ci/quality-gates`

---

## Purpose

Automatically catch overfit strategy commits before they reach master. Specifically: any PR that adds or modifies a gate_v2 verdict file must be accompanied by evidence that the strategy's Probability of Backtest Overfit (PBO) is below the risk threshold.

The gate is designed to be **loud, informative, and hard to bypass by accident** — but with a documented override path for edge cases where the CI check is wrong.

---

## The three-tier policy

| PBO range | Action | UX |
|---|---|---|
| `< 0.30` | Silent pass | PR check goes green |
| `0.30 ≤ PBO < 0.40` | **Warning** (does not block) | PR check goes yellow. A comment is posted listing which verdicts crossed the warning threshold and why. Merge is allowed. |
| `PBO ≥ 0.40` | **Hard block** | PR check goes red. Comment posted. Merge is blocked by branch protection. |
| `PBO missing` on a PASS verdict | **Warning** | Missing PBO on a verdict claiming PASS is suspicious — flag it but don't block, in case older verdicts lack the metric. |
| Verdict FAILs (any PBO) | Silent pass | Failed verdicts are already blocked by their own verdict field — no PBO gate needed. |

## Why 0.40 as the hard-block threshold

The funnel's own threshold (per `tools/jarvis-funnel/references/thresholds.md`) is `PBO < 0.40` for Tier A. The CI gate simply mirrors that threshold. Rationale:

- Lopez de Prado's textbook recommendation is PBO < 0.50 (better-than-coin-flip)
- Funnel tightens to 0.40 to account for "moderately aggressive" tier calibration
- Below 0.40 the strategy has less than a 40% chance of being pure overfit noise
- At exactly 0.40 the CI gate blocks — no rounding-favor for borderline cases

The 0.30 warning band exists because PBO estimation is noisy — a strategy with true PBO = 0.35 could measure at 0.42 with high enough variance to matter. The warning gives you a chance to look at the strategy before it flips to a block on the next re-run.

## Why not block on other funnel gates too?

Deliberately narrow scope for the first iteration:

- **PBO is the single most important overfit signal** in the funnel gate list (it's Gate 2)
- Other gates (DSR, PF CI, permutation p-value) can also be added later — same script pattern
- Starting with PBO alone means the CI is fast (< 1 second per verdict), false-positive rate is low, and the fix path is clear (either lower the parameter count, or wait for more OOS data)

Adding more gates is a follow-up PR against `ci/quality-gates`.

## The override path

Sometimes the gate is wrong. Examples:
- Strategy is a specialist that only trades in one regime, PBO calculated across all regimes is inflated
- Verdict file being modified is an archive artifact, not a new PASS claim
- Deliberately committing a known-overfit strategy for research purposes

Override mechanism (in order of preference):

1. **Explain in the PR body** with the label `funnel-override: <reason>`. The gate still runs and posts its comment, but the merge doesn't require green — a reviewer with write access can force-merge. The override reason lives in the PR history forever.

2. **Add the verdict file to `scripts/ci/pbo_gate_exemptions.txt`** (path per line). The gate skips these files. Exemptions require a matching comment explaining why. Use sparingly — every exemption weakens the gate.

3. **Change the threshold globally** in `scripts/ci/check_pbo_gate.py`. Requires its own PR and reviewer approval. Every threshold change appends to the changelog in `tools/jarvis-funnel/references/thresholds.md`.

**What is NOT an override path:** deleting the workflow file, temporarily disabling the check in `paths:`, or removing the branch protection rule. Any of those in a PR is itself a red flag.

## What the PR comment looks like

The workflow posts a comment on every PR that touches verdict files. Example:

```
## Funnel PBO Gate

**3 verdict file(s) checked**

### ❌ Blocking issues (1)
| File | Symbol / Family / Rank | PBO | Reason |
|---|---|---|---|
| `engine/data/gate_v2_verdicts/MES_trend_rank12.json` | MES / trend / 12 | 0.47 | PBO 0.47 >= 0.40 block threshold |

### ⚠️ Warnings (1)
| File | Symbol / Family / Rank | PBO | Reason |
|---|---|---|---|
| `engine/data/gate_v2_verdicts/MNQ_breakout_rank3.json` | MNQ / breakout / 3 | 0.34 | PBO 0.34 in warning band [0.3, 0.4) |

### ✅ Clean (1)
- `engine/data/gate_v2_verdicts/MGC_trend_rank5.json` — MGC / trend / 5
```

The comment is regenerated on every push to the PR so it always reflects the latest state.

## Interaction with other CI jobs on the same workflow

The `funnel-quality-gate.yml` workflow has four jobs that run in parallel:

1. `test-funnel-gate` — pytest against the funnel_gate test suite (locks in the intentional rank3-style divergences from gate_v2)
2. `test-meanrev-v2` — pytest against the meanrev_v2 signal tests
3. `pbo-gate` — the PBO check documented here
4. `rationale-check` — blocks new `run_*.py` files that lack an economic rationale in their docstring

**All four must be green for merge.** If any single one fails, the PR is blocked. This is intentional: the funnel skill's core thesis is that strategies without documented rationale and without overfitting checks should never reach production, and CI is the enforcement layer.

## Expected false-positive rate

PBO estimation is noisy. Rough expectation from the current codebase:

- ~5% of Tier A candidates will land in the 0.30–0.40 warning band on any given run
- ~1% will legitimately cross 0.40 and be genuinely overfit
- ~0.5% will cross 0.40 due to estimator noise on a strategy that would actually be safe

The false-positive rate is acceptable because the override path is documented and the cost of a false positive (one comment + one manual review) is much lower than the cost of a false negative (an overfit strategy reaching paper trading).

## Metrics to watch after rollout

Once merged, we should track:
- Fraction of PRs that trigger the PBO gate (any status)
- Fraction that get blocked
- Fraction of blocked PRs that get overridden vs. actually revised

If override rate > 30%, the threshold is probably too strict for current data quality. If block rate is 0% for 3 months, the threshold might be too loose. Weekly PR health report (via `branch-hygiene.yml`) will surface these ratios in the summary issue.

## Rollout sequence

1. Merge `ci/quality-gates` PR (this branch)
2. Do NOT enable branch protection rules that require this workflow yet
3. Let the workflow run on the next 3-5 PRs, review the comments manually
4. Once comments look useful and false-positive rate is low, enable branch protection to require `pbo-gate` as a required check
5. After 30 days, review the metrics above and adjust thresholds if needed

---

## What this doc does NOT cover

- Real-time PBO computation from scratch (that lives in `engine/backtest/family_fdr.py` and is called during backtests, not in CI)
- Verdicts produced outside the standard funnel path (manual research reports, external data). Those are checked at the point of intake into the funnel via `phase1_inventory.py`, not at the CI layer.
- Historical verdict re-audits. If we later change the PBO computation methodology, we need a separate migration PR that re-runs PBO across the entire archive and doesn't get gated on the pre-migration values.
