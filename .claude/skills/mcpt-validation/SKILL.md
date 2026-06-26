---
name: mcpt-validation
description: Run and interpret bar-permutation Monte Carlo permutation tests (MCPT) on a jarvis-trader strategy to tell real edge from data-mining bias. Use when the user says "is this strategy real or random", "run MCPT", "permutation test this backtest", "is this overfit", "p-value on this strategy", "did the optimizer find noise", or before promoting any new strategy candidate. Wraps engine/analytics/permutation_test.py — does not re-implement the math. Produces a four-gate verdict (PASS / REJECT-with-gate) plus the p-values and the lock-spec discipline check.
---

# When to use

After a backtest looks good and BEFORE trusting it — MCPT answers "would my optimization process have found this edge in pure noise?". Trigger before promoting any new strategy candidate to paper, or whenever a backtest looks suspiciously clean (Sharpe > 3, near-zero drawdown, PF > 2.5 on a short window).

This is the **bar-permutation** null (Masters 2020) — it permutes price bars and re-runs the optimizer. It is distinct from `monte_carlo.py` (which shuffles a realized trade list). Use this one to catch *data-mining / optimization bias*; use the trade-shuffle for "given these trades, is the equity curve lucky ordering?".

# Hard precondition — lock the spec first

MCPT is only valid if the strategy specification is fixed BEFORE the test runs. If the user wants to "tweak and re-run until it passes", STOP and say so: that data-mines the p-value itself (the most insidious failure mode). One run per locked spec. A fail means discard the strategy, not adjust it.

# How to use

## Inputs needed

1. An OHLC DataFrame (`open/high/low/close`, datetime index) for the instrument/timeframe.
2. `optimize_fn(df) -> (params, profit_factor)` — the parameter search.
3. `walkforward_fn(df, train_window) -> profit_factor` — the rolling walk-forward.
4. `train_window` — bars in the first training fold.

## Run it

```python
from analytics.permutation_test import validate_strategy

result = validate_strategy(
    df, optimize_fn, walkforward_fn,
    train_window=TRAIN_BARS,
    n_insample_perms=1000,   # cheap; lower to ~200 for a quick read
    n_wf_perms=200,          # expensive (re-runs full walk-forward each time)
    long_history=False,      # True for >= ~2yr OOS -> stricter walk-forward alpha
)
```

For a single test rather than the full pipeline, call `run_insample_mcpt` or `run_walkforward_mcpt` directly (same module).

## Thresholds (mechanical — from permutation_test.py / ml-pitfalls-defense.md)

- In-sample MCPT: **p < 0.01** to pass (`INSAMPLE_ALPHA`)
- Walk-forward MCPT: **p < 0.05** (`WF_ALPHA`), or **p < 0.01** for >= ~2yr OOS (`WF_ALPHA_LONG`)

# Report template (use exactly this structure)

```
# MCPT — <instrument> <timeframe> <window>

## Verdict
<one line: result["verdict"] + plain-English meaning>

## Gates
| Gate | Stat | Threshold | Result |
| ---- | ---- | --------- | ------ |
| 1 In-sample excellence | PF = <is_pf> | > 1.0 | <pass/fail> |
| 2 In-sample MCPT       | p = <is_pval> | < 0.01 | <pass/fail> |
| 3 Walk-forward         | PF = <wf_pf> | > 1.0 | <pass/fail/not-run> |
| 4 Walk-forward MCPT    | p = <wf_pval> | < 0.05 | <pass/fail/not-run> |

## Read
<2-3 sentences. If REJECT, name WHICH gate and what it means: e.g. "p=0.76 in-sample
means 76% of random shuffles of this market produced an equal-or-better optimized PF —
the optimizer eats noise as easily as signal, so there is no edge.">

## Next Actions
<1-2 steps. On PASS: "candidate, not a guarantee — confirm on a second regime/market."
 On REJECT: "discard the spec; do NOT re-tune against this data.">
```

# Hard rules

- Fail-closed: `validate_strategy` stops at the first failing gate and does not run later ones. Report the un-run gates as "not-run", not "pass".
- A PASS is a **candidate, not a guarantee** — never recommend live trading on one MCPT pass. Masters: pass it across multiple regimes/markets before trusting it.
- Small samples lie: with < ~30 trades the p-value is low-power. Say so explicitly (MES has ~16, MGC ~67 — a single pass there is weak evidence).
- Volatility-clustering / lead-lag strategies get a small optimistic bias *against* them under the default shuffle. For regime-persistence strategies note that `get_block_permutation` is the fairer null.
- Do NOT present MCPT as a blocking gate — as of this writing it is a diagnostic; gate wiring is a deferred `[safety-review]` change.
