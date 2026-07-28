# ATR Trailing Stop — ThinkorSwim built-in

**File**: _none_ — this is a ThinkorSwim **built-in** study, not a custom `.ts` in this repo
**Author**: ThinkorSwim built-in (Sylvain Vervoort ATR stop-and-reverse method)
**Chart legend**: `ATRTrailingStop (modified, 5, 3.5, long, WILDERS)`
**JARVIS Layer**: Layer 5 Sizing (the stop line) + Layer 4 Entry (the bounce hypothesis)
**Status**: Ported (2026-06-24)
**Python counterpart**: `engine/backtest/indicators.py::atr_trailing_stop`
**Signal module**: `engine/backtest/atr_trail_bounce_signals.py`
**Panel**: Upper (price chart)

## Why this doc exists

This is the **dotted blue line** on Matt's /ES 5m chart that price was observed
bouncing off precisely (2026-06-24). It was the only major study in that view
with no engine counterpart — every other study (Saty ATR Levels, Corey
Tscore/TPO, Keltner 3.01) was already ported. This doc and the two modules
above close that gap and, more importantly, make the "price bounces off the
line" claim **testable** instead of visual.

It is intentionally **not** an entry in `registry.yaml`: that file is keyed on
real shareable `.ts` files (its schema requires a `file:` path and its loader
test locks the script count), and this is a ThinkorSwim built-in with no `.ts`.
This doc is its home in the bridge.

**Provenance note (2026-07-28)**: `engine/backtest/atr_trail_bounce_signals.py`
was added in commit `bca09e5`, whose message ("docs: analyze
Alishahryar1/free-claude-code as noise, not integrated (#436)") describes an
unrelated repo evaluation, not this file. The diff is correct and reviewed —
only the commit message is mislabeled. Recorded here (and as a `git notes`
annotation on `bca09e5`) rather than rewritten, since amending a commit that
old on `master` would rewrite every commit after it.

## What the line is

A stop-and-reverse trailing stop. It trails **below** price while long (acting
as support) and **above** price while short (acting as resistance), flipping
state when price closes through it. The "modified" variant uses TOS's
HiLo/HRef/LRef true-range formulation; `WILDERS` is the smoothing.
`engine/backtest/indicators.py::atr_trailing_stop` reproduces this faithfully
so the engine's line matches the chart bar-for-bar.

## The alpha hypothesis (and how it is being tested)

There are **three rules** the line can generate, all implemented and backtested
separately so their edges can be compared and attributed:

- **Bounce** (`generate_atr_trail_bounce_signals`): long when a bar wicks
  to/through the line while in long state **and** closes back above it
  (`touch + reclaim`), **and** the line stays in long state for `hold_bars`
  afterward (Matt's "does it stay above after 5 min" confirmation). Mirror for
  shorts. Stop = the line. Targets = {1.5, 2.618} x ATR(14). This is a
  defined-target continuation trade.
- **Flip** (`generate_atr_trail_flip_signals`): enter the bar the line flips
  (close crosses through it) — this is what the TOS built-in strategies
  `ATRTrailingStopLE` / `ATRTrailingStopSE` actually trade (the `-100 (-5000)` /
  `100 (5000)` fills on Matt's chart). Stop-and-reverse, trend-following: stop =
  the line, targets are R-multiples (2/3/4 R) but the real exit is the *opposite
  flip*, so it is backtested with `use_targets=False` + trailing exit + 1
  contract (the SMA-trend harness convention).
- **Confluence** (`generate_atr_trail_confluence_signals`): the flip base, but
  entries that fight the prior-session value area are dropped (long requires
  price not BELOW_VAL, short not ABOVE_VAH; `strict_confluence=True` requires
  the confirming extreme). Motivated by Matt's live episode where the flip-short,
  the VAL break, and the TPO target all agreed before a clean move. The
  value-area reference comes from `tpo_profile.compute_tpo_profile`, which is
  shifted one session — so it uses only the *prior* completed session, no leak.
  Confluence trades are a strict subset of the flip trades, so the side-by-side
  backtest shows exactly what the gate adds or costs.

- **Kelt-confluence** (`generate_atr_trail_kelt_confluence_signals`): the flip
  base, gated by the **4-hour Keltner channel** (the `kelt_3.01` study on the
  chart). `strict_kelt=False` keeps longs above the 4H Keltner basis / shorts
  below it (channel half); `strict_kelt=True` requires a 4H band breakout
  (long ≥ upper, short ≤ lower). Strict ⊆ loose ⊆ flip. The 4H Keltner is
  `indicators.keltner_channels_mtf` (developing aggregation, point-in-time safe).

All variants are point-in-time clean: the decision at bar `i` reads only bars
`<= i` (enforced by truncation-invariance unit tests for each).

## On the kelt_3.01 Keltner port

`indicators.keltner_channels` reproduces the `jp_keltner_multi_timeframe.ts`
math (SMA basis ± factor·SMA(TrueRange)) but only on the base bar timeframe.
`indicators.keltner_channels_mtf` adds the `iAggregationPeriod` behaviour:
aggregate base bars to `rule` (e.g. `"4h"` = FOUR_HOURS), compute the Keltner
there, map back to base bars. With `rule` equal to the base frequency it
collapses exactly to `keltner_channels` (unit-tested). `developing=True`
matches the TOS line (current higher-TF bar is the developing aggregate);
`developing=False` uses only completed higher-TF bars.

This is exactly the kind of claim that survives in *random* data (a trailing
stop hugs price by construction), so both variants are gated by MCPT, not
trusted on sight.
- **Validation** (`run_atr_trail_bounce.py`): grid-search the locked spec, run
  the event-driven `Backtester`, then bar-permutation MCPT
  (`analytics.permutation_test.validate_strategy`). PASS requires in-sample
  MCPT `p < 0.01` and walk-forward MCPT `p < 0.05`. A REJECT means **discard**,
  not re-tune (see `.claude/rules/ml-pitfalls-defense.md`).

## TOS Inputs (match these to reproduce the chart line)

| Input | Chart value | Notes |
|---|---|---|
| `trailType` | modified | HiLo/HRef/LRef true range |
| `ATRPeriod` | 5 | fast — hugs price closely |
| `ATRFactor` | 3.5 | band width multiplier |
| `firstTrade` | long | seeds initial state |
| `averageType` | WILDERS | Wilder smoothing |

## Locked param grid for MCPT

`factor in {3.0, 3.5, 4.0}`, `hold_bars in {0, 1, 2}`,
`touch_tol_atr in {0.0, 0.10}`, `atr_period = 5` (fixed). Lock before running;
do not iterate against the p-value.

## How to run (locally — needs data + venv)

```bash
cd engine
.venv/Scripts/python -m backtest.run_atr_trail_bounce --symbol MES --timeframe 1h
.venv/Scripts/python -m backtest.run_atr_trail_bounce --symbol MES --timeframe 5m \
    --data-file backtest/cache/MES_..._5m.csv
```

The web/CI container has no bars, so this is a local run. Unit tests
(`engine/tests/test_atr_trail_bounce_signals.py`) run anywhere — synthetic data.
