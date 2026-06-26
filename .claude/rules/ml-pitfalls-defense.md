---
paths:
  - "engine/backtest/**"
  - "engine/strategies/**"
  - "engine/strategy_lab/**"
  - "engine/analytics/validation_metrics.py"
  - "engine/optimization/**"
---

# ML Trading Pitfalls — Defensive Checklist

Companion to `backtest-signals.md`. That rule covers *which numbers* to gate
on (STC, ATR, WFE >= 0.5, etc.); this rule covers *why those numbers can lie*
and what to do about it.

Synthesized from **López de Prado, _Advances in Financial ML_** (Wiley 2018;
core chapters also published as SSRN working papers 2016-2018) and
**Aronson, _Evidence-Based Technical Analysis_** (Wiley 2006). Papers cited
by DOI / SSRN where possible so this rule survives any link-rot in
third-party curated lists.

> **Scope.** Trigger this checklist on ANY change to: backtest harness,
> walk-forward runner, strategy optimizer, RL reward function, hyperparameter
> search, or any code that promotes a number (PF / Sharpe / WFE) into a
> go/no-go decision. Do NOT trigger for signal-generation edits already
> covered by `backtest-signals.md`.

## The 9 pitfalls — status in jarvis-trader

| # | Pitfall | Current defense | Gap |
|---|---|---|---|
| 1 | Train-test leakage (serial correlation across fold boundaries) | Walk-forward eval in `engine/backtest/rolling_wfe_scheduler.py` | **No PurgedKFold / CombinatorialPurgedKFold**. mlfinlab is listed in `jarvis-search-discipline` as a preferred lib but **not installed** (verified 2026-04-17: only referenced in `engine/tests/conftest.py`). If CV-based model selection is ever added (e.g. for meta-labeling), PurgedKFold is required, not optional. |
| 2 | Embargo period | None | **Gap.** When/if CV is added, set embargo >= max holding period (for MCL 1h: 4-8 bars minimum). |
| 3 | Sharpe ratio inflation from multiple testing | **DSR implemented & gated in the gate-v2 candidate path**: `engine/backtest/deflated_sharpe.py` (Bailey & López de Prado, SSRN-2460551) via `_gate_v2_trade_metrics.trade_level_dsr`, gated on `GATE_DSR` (0.10) / `GATE_DSR_ALT` (0.30) and recorded in every gate-v2 verdict + the calibrator. | **Narrow remaining gap** (the prior "no DSR" note was stale). DSR is NOT used in (a) `analytics/validation_metrics.py` `composite_score` (still blends 4 metrics without it), nor (b) the `forward_test.py` live-lineage graduation path — the unit that actually trades, which has no DSR at all. Both are candidates for a future report-only diagnostic first, then a `[safety-review]`/Tier-3 gate; the forward-test lineage is statistically thin, so a diagnostic should precede any gate. |
| 4 | Data-snooping bias | OOS test set held to 2025 data per `backtest-signals.md:46` | **Partial.** Discipline exists but nothing mechanically prevents someone from iterating against the OOS set until it contaminates. Fix: write `2025_oos_access_count` to `engine/data/optimization_log.jsonl` each time and hard-cap at a small number (e.g. 3 prod promotions per quarter). |
| 5 | Meta-labeling | None | Not a gap — this is an **opportunity**, not a defense. Meta-labeling (López de Prado ch. 3) separates direction-of-trade from take-the-trade probability. Could be wired as a secondary filter on top of existing `debate.py` votes without breaking the IC-weighted ensemble. Out of scope for this rule — track as a feature candidate. |
| 6 | Fractional differentiation (stationarity vs memory tradeoff) | `pandas.diff()` is used ad-hoc in indicator code | Gap for regime-detection features that consume price level directly (vs returns). If/when `engine/analysis/regime.py` adds a "price relative to fair value" feature, reach for `mlfinlab.features.fracdiff` rather than integer differencing. |
| 7 | Chart-pattern subjectivity | N/A — no visual classification in production debate (Pattern Vision Analyst is scaffold only, not live-wired as of `a217dd0`) | Becomes live when Pattern Vision Analyst is wired. See `engine/agents/pattern_vision_analyst.py` — classifier returns structured `VisionClassification`, not free-form text, which mitigates but does NOT eliminate subjectivity risk. The 30-setup eval replay named in the scaffold's NEXT STEPS block is how we measure this — do not ship live wiring without it. |
| 8 | Survivorship bias | CME futures (MCL / MNQ / MES) — survivorship doesn't apply to active contracts | N/A for futures. Would matter if equities universe is ever added. |
| 9 | Monte Carlo permutation tests | **Both nulls implemented (as diagnostics).** (a) *Bar-permutation MCPT* (Masters 2020): `engine/backtest/bar_permute.py` permutes price bars, `engine/analytics/permutation_test.py` re-optimizes on each (`run_insample_mcpt`, `run_walkforward_mcpt`, `validate_strategy`). (b) *Trade-sign shuffle* (Aronson ch. 6): `permutation_test.permute_and_score(trades, n_iters=500, metric=...)` builds a no-edge null by negating each trade's P&L and rescoring. | **Remaining: gating only.** Both tests exist and are tested but are **diagnostics, not blocking gates**. Wiring (a) into the gate-v2 optimizer and (b) into `forward_test.py` graduation (its correct null — the live entry path is LLM-driven, not a mechanical optimizer) is deferred to a `[safety-review]` PR: both change trade authorization, and small-sample power on the 16-trade (MES) / 67-trade (MGC) series must be observed before either blocks. |

## Numerical gates — WFE table addendum

Existing: `backtest-signals.md` requires WFE >= 0.5 for paper.

Proposed additions (not yet enforced in code — targets for follow-up PR):

```
WFE >= 0.5                       -> existing gate (keep)
DSR >= 0.10 / 0.30 (alt)         -> Deflated Sharpe (IMPLEMENTED & gated in gate-v2; absent from composite_score and the forward_test lineage path)
insample_mcpt_p < 0.01           -> bar-permutation re-optimize null (IMPLEMENTED; diagnostic, not yet gating)
walkforward_mcpt_p < 0.05 (<0.01 for 2yr+)  -> bar-permutation walk-forward null (IMPLEMENTED; diagnostic)
trade_shuffle_p < 0.05           -> >=500-iter sign-shuffle of realized trades (IMPLEMENTED: permute_and_score; diagnostic, forward_test null)
max_dd_recovery_bars <= 2*lookback  -> drawdown must recover within 2x the feature lookback
oos_access_count <= 3/quarter    -> mechanical OOS contamination cap
```

Bar-permutation MCPT — how to invoke (diagnostic):

```python
from analytics.permutation_test import validate_strategy
# optimize_fn(df) -> (params, pf); walkforward_fn(df, train_window) -> pf
verdict = validate_strategy(df, optimize_fn, walkforward_fn, train_window=TRAIN_BARS)
# verdict["verdict"] in {PASS, REJECT (in-sample excellence|in-sample MCPT|walk-forward|walk-forward MCPT)}
```

Discipline: lock the strategy spec BEFORE running. A fail means discard the
strategy, not tweak-and-rerun — iterating against the test data-mines the
p-value itself (the most insidious failure mode; Masters ch. on target-fiddling).

The first three are the ones most worth implementing. The fourth and fifth
are stretch goals — useful but incremental over the existing WFE gate.

## What to do when you hit a gap

Rank order:

1. If the change is on the **hot path** (signal generation, execution, risk) —
   do NOT block on adding new statistical defenses. Ship with existing gates.
2. If the change is a **new optimizer / search** — DSR gate is mandatory.
   Without it, "best params" is a hallucination.
3. If the change is a **new strategy candidate for paper promotion** —
   permutation test is mandatory. One 500-iter run costs ~seconds on MCL 1h.
4. If the change is a **meta-labeling layer** or any other CV-based selection
   — PurgedKFold is mandatory, embargo >= 8 bars for 1h, >= 30 bars for 5m.

## Installation prerequisite

`mlfinlab` is a preferred library in `jarvis-search-discipline` but **not
installed** in `engine/requirements.txt` (verified 2026-04-17). Adding it
pulls `scikit-learn`, `numba`, and `joblib` — the numba dep is the tricky
one on Windows. Test install in a throwaway venv before committing to
`requirements.txt`.

If `mlfinlab` install is brittle, individual papers can be implemented
directly from primary sources:

- PurgedKFold: López de Prado, *Advances in Financial ML* ch. 7, ~40 lines of NumPy.
- DSR: Bailey & López de Prado, SSRN-2460551. ~30 lines.
- Permutation test: Aronson EBTA ch. 6. Pure NumPy.

Hand-rolling against primary sources keeps the dependency surface thin.

## Anti-patterns

- Reporting a single Sharpe / PF / WFE number without the sample size and
  the number of candidate strategies that produced it. The maximum of N
  backtests is not an estimator of the best strategy's true Sharpe.
- "Just one more parameter tweak" against the 2025 OOS set. That's data
  snooping in slow motion.
- Using train/test split on time-series data without purge + embargo.
  `sklearn.model_selection.train_test_split(shuffle=True)` is a correctness
  bug in a trading context; `shuffle=False` alone is not sufficient if
  features or labels straddle adjacent bars.
- Promoting an RL agent to paper from a training reward curve without a
  sealed OOS walk-forward. Training reward can be fit arbitrarily well.
- Quoting a live metric without acknowledging the cost model applied to it.
  Commission matters. `engine/strategies/rl_environment.py:533-541` deducts
  it; ad-hoc backtest scripts often don't.

## Cross-references

- `backtest-signals.md` — canonical signal params + WFE paper/halt thresholds
- `engine/analytics/validation_metrics.py:273` — composite_score weights
- `engine/backtest/rolling_wfe_scheduler.py` — walk-forward runner
- `engine/strategies/rl_config.py` — experiment-history comment log (Run 1-11)
- `docs/repo-integrations/grananqvist__awesome-quant-machine-learning-trading.md` — source analysis for this rule

## Attribution

Pitfalls 1-6, 8: López de Prado, *Advances in Financial Machine Learning*,
Wiley 2018. SSRN working papers: SSRN-2460551 (Deflated Sharpe Ratio),
SSRN-2846466 (Meta-Labeling), SSRN-2545220 (Purged CV).

Pitfalls 4, 7, 9: Aronson, *Evidence-Based Technical Analysis*, Wiley 2006.

Survey pointer (not cited as source; used only to index the papers):
`docs/repo-integrations/grananqvist__awesome-quant-machine-learning-trading.md`.
The curated list itself has no LICENSE — we cite the underlying papers
directly from SSRN / Wiley / arXiv.
