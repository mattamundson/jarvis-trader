# Index Breakout — Locked Strategy Specification

_Origin: critique of the ChatGPT "Simple Nikkei Breakout Strategy" reconstruction
(Breakout Trading Academy). This document is the **lock-before-you-run** artifact that the
MCPT discipline (`.claude/rules/ml-pitfalls-defense.md`) requires. Lock the spec, run the
test, accept the verdict. A FAIL means discard — not tweak-and-rerun._

Status: **DIAGNOSTIC / candidate.** Not approved for paper. No `engine/config.py`,
`engine/risk/`, or kill-switch code is touched by this work.

---

## 0. The honest framing (read first)

Three facts decided the shape of this spec:

1. **The engine already is the institution-grade platform.** Look-ahead-safe event-driven
   backtester (`engine/backtest/backtester.py` — fills at next-bar open, adverse slippage +
   half-spread, ATR sizing, kill switch), Donchian breakout signals with EMA-trend and
   ATR-expansion regime gates already built in (`engine/backtest/breakout_signals.py`),
   four-gate bar-permutation MCPT (`engine/analytics/permutation_test.py`), Deflated Sharpe
   (`engine/backtest/deflated_sharpe.py`), Monte Carlo (`engine/backtest/monte_carlo.py`),
   rolling walk-forward (`engine/backtest/rolling_wfe_scheduler.py`). The ChatGPT plan
   proposed to rebuild all of this from a `yfinance` script. We reuse it instead.

2. **There is no Nikkei here.** The data path is Polygon (`engine/backtest/data_loader.py`);
   the free tier is futures-blocklisted and there is no NKD/NIY/NK feed or contract spec in
   `engine/backtest/contract_specs.py`. A literal Nikkei backtest is not reproducible in
   this repo. The strategy is therefore validated on the CME index micros the engine
   actually trades, and **the Nikkei conclusion is explicitly out of scope until a feed is
   wired** (see §7).

3. **The nearest analog already failed here.** Per `engine/CLAUDE.md`, MNQ (Micro Nasdaq)
   breakout "all fail gate v2 (55 trades, 0 wins, 2026-05-06/07)" and M2K Donchian rank-1
   FAILED (`p_edge=0.50`, `wfo=WEAK`, 2026-05-24). An hourly index breakout is not a fresh
   idea in this codebase — it is a previously-rejected one. This spec re-tests it honestly;
   the prior rejections are the benchmark to beat, not noise to ignore.

---

## 1. Hypothesis (falsifiable, one sentence)

> On a liquid equity-index micro future, a close beyond the prior *N*-bar Donchian channel
> marks a range expansion that continues far enough, often enough, to overcome an ATR-based
> stop **and** realistic transaction costs — producing a profit factor whose excess over 1.0
> is not explainable by data-mining a noise series.

If that is false, there is no edge and we stop. The test in §5 is built to try to falsify it.

**Why this and not ChatGPT's `EMA20 ± 0.75·ATR`:** that rule is "price slightly above a
moving average" — a momentum *condition* that is true on most bars of any uptrend, not a
discrete breakout *event*. ChatGPT then ANDed it with `ADX < 20` (no-trend) and a "let it
run" Chandelier exit (trend-following) — three mutually contradictory regimes. A Donchian
channel break is an actual event with a clean point-in-time definition (`close > max(high,
N).shift(1)`), already implemented and warm-up-guarded in `breakout_signals.py`.

---

## 2. Universe & data

| Item | Decision | Rationale |
|---|---|---|
| Instruments | MNQ, MES, M2K (index micros). Default validation symbol: **MNQ** | Nearest liquid analog to a Nikkei index breakout; has the documented prior rejection to beat |
| Timeframe | 1h bars | Matches the engine's approved instruments and the existing cache/WFO cadence |
| Costs | From `contract_specs.py` (e.g. MNQ: mult $2/pt, 0.25 tick, $0.62/leg, **2-tick** slippage) | Empirical IB tier-1 + observed 1h slippage; MNQ gaps 2 ticks, not 1 |
| Data integrity | Bar-quality gate screens every load; MCPT refuses silent synthetic data | `data_loader._screen_bar_quality`, `run_mcpt._warn_if_sample` |

**Timeframe honesty:** ChatGPT's day-of-week and 09:30–11:00 session filters are meaningless
on daily bars and out of scope here on 1h bars without a separate intraday study. They are
**not** in this spec.

---

## 3. The rules (exact, mapped to code)

Entry / stop / exit are **not reimplemented** — they are
`generate_donchian_breakout_signals(...)` in `engine/backtest/breakout_signals.py`:

| Component | Rule | Param (default) |
|---|---|---|
| Long entry | `close > rolling_max(high, N).shift(1)` | `donchian_period = N` |
| Short entry | `close < rolling_min(low, N).shift(1)` | symmetric |
| Stop | `entry ∓ stop_atr_mult · ATR(14)` (Wilder) | `stop_atr_mult` |
| Exit | close re-enters the prior-bar channel (reversion-complete) | — |
| Fill | **next bar open**, after adverse slippage + half-spread | `backtester._process_pending_entry` |
| Sizing | `contracts = (capital · 1%) / (stop_distance · multiplier)`, integer, capped | `backtester._calculate_contracts` |

**One position-sizing framework only:** fixed-fractional 1% risk. ChatGPT stacked
fixed-%, volatility-targeting, *and* Kelly *and* correlation weighting — three conflicting
sizers with no defined precedence. We use one. Volatility targeting and Kelly are explicitly
rejected for this candidate (see §6).

### Locked parameter grid (deliberately tiny)

```
donchian_period ∈ {15, 20, 25}
stop_atr_mult   ∈ {1.5, 2.0}
→ 6 combos
```

Regime gates (`ema_trend_period`, `atr_regime_mult`) and the volume filter (`vol_mult`) are
present in the signal but **OFF** in this baseline. Add-one-filter-at-a-time is a *separate*
locked spec and a *separate* MCPT run — bolting them on now would re-inflate the
multiple-testing penalty the small grid exists to control. Six combos is the whole point:
the maximum of *N* backtests overstates the best strategy's true Sharpe by ≈√(2·ln N), so
*N* is kept small and is fed to Deflated Sharpe as `n_trials` honestly.

---

## 4. What success must clear (gates fixed BEFORE running)

A candidate is promotable to the next stage **only if all hold**:

| Gate | Threshold | Source |
|---|---|---|
| Trade count | ≥ 100 OOS trades across the walk-forward | small-sample PF is a coin flip below this |
| In-sample excellence | optimized PF > 1.0 | `validate_strategy` gate 1 |
| In-sample MCPT | `p < 0.01` | gate 2 — optimizer can't find this edge in noise |
| Walk-forward OOS | aggregate PF > 1.0 | gate 3 |
| Walk-forward MCPT | `p < 0.05` (`< 0.01` if ≥ 2yr OOS) | gate 4 |
| Deflated Sharpe | `DSR ≥ 0` after `n_trials = 6` correction | `deflated_sharpe.py` |
| **Cost survival** | PF > 1.0 still holds at the **realistic** cost tier, reported as **% of gross edge eaten** | the single most important futures check |

The cost line is non-negotiable and is the one ChatGPT's delivered code omitted entirely
(it *listed* commissions/slippage, then shipped a backtest with neither). For a micro future
churning on 1h breakouts, costs can eat the whole edge; if gross PF is 1.10 and costs take it
under 1.0, the strategy is dead regardless of how pretty the in-sample curve looks.

**Kill criteria (discard, do not tune):** any gate fails → the candidate is rejected and
this spec is closed. Re-running with tweaked params against the same data is data-snooping
the p-value itself (Masters; `ml-pitfalls-defense.md`). A new idea gets a new locked spec.

---

## 5. How to run it (on a data-equipped machine)

This container has no market data, no Polygon key, and no scientific-Python venv, so the
verdict is produced on Matt's Windows box, not here.

```bash
cd engine
# 1) ensure a 1h cache exists for the symbol (backtest/cache/MNQ_*_1h.csv)
# 2) four-gate bar-permutation MCPT on the breakout signal via the REAL Backtester:
.venv/Scripts/python -m backtest.run_mcpt prices --symbol MNQ --strategy breakout \
    --train-window 600 --insample-perms 300 --wf-perms 100
# verdict line: PASS | REJECT (in-sample excellence | in-sample MCPT | walk-forward | walk-forward MCPT)

# Plumbing smoke test with clearly-labeled SYNTHETIC data (meaningless p-values, wiring only):
.venv/Scripts/python -m backtest.run_mcpt make-sample --symbol MNQ
.venv/Scripts/python -m backtest.run_mcpt prices --symbol MNQ --strategy breakout
```

The `--strategy breakout` path reuses the existing four-gate validator, the production
Backtester (next-bar fill + real costs), and the PF cap — only the signal and its 6-combo
grid are new. `--strategy trend` (default) is unchanged.

Follow-on once the MCPT verdict is in hand — the full gate-v2 CORE/ALT verdict (bootstrap PF
CI, `p_edge`, MC 95th-pct drawdown, 4-tier cost sweep, Deflated Sharpe) with the ≥100-trade
floor wired in:

```bash
.venv/Scripts/python backtest/run_index_breakout_gate_v2.py --symbol MNQ
# writes engine/data/gate_v2_verdicts/MNQ_breakout_rank1.json
```

`run_index_breakout_gate_v2.py` mirrors the established `run_m2k_donchian_rank1.py` template
(same rolling-WFO windows, same gate thresholds) and reuses the production Backtester +
`generate_donchian_breakout_signals` — nothing in the execution or gate math is
re-implemented. Run the four-gate MCPT first; if it REJECTs, there is no point running the
heavier gate-v2 sweep.

---

## 6. Explicitly rejected (and why)

ChatGPT's "22 layers / institutional architecture" is mostly degrees of freedom sold as
robustness. Rejected for this candidate:

- **XGBoost meta-filter (`P(win) > 0.6`), Hidden Markov regime engine** — need thousands of
  clean trades; on a few-hundred-trade 1h series they are overfit generators, and per-trade
  win-probability labeling is the same outcome→same-bar-decision leak `testing.md` forbids.
- **Genetic-algorithm parameter search on `Sharpe·CAGR/MaxDD`** — optimize-then-validate is
  the curve-fit loop; we permutation-test the *minimal* rule first.
- **Volatility targeting AND Kelly AND correlation weighting** — three conflicting sizers; we
  use fixed-fractional only.
- **Adaptive ATR multiplier (1.2/0.8/0.5 by vol)** — invented constants; ATR is already the
  vol unit, so an inverse-vol multiplier on top double-counts.
- **Ensemble weights 40/30/20/10** — pulled from air, no derivation.
- **Cross-validation on ES/NQ/YM/RTY as "anti-overfit"** — those are ~0.9 correlated; "works
  on 5 markets" is one bet, not five, and cherry-picking across them *inflates* multiple
  testing rather than controlling it.

These are not banned forever — they are out of scope for *this* locked spec. Each would be a
separate hypothesis with its own lock + MCPT, added only after the baseline shows an edge to
filter.

---

## 7. The Nikkei gap (open, explicit)

A genuine Nikkei breakout requires: (a) a real OHLC feed for NKD/NIY (CME) or the Osaka/SGX
contract, (b) a `ContractSpec` (multiplier, tick, JPY→USD handling, commission, observed
slippage), (c) its own holiday/session calendar. None exist in this repo today. Until they
do, MNQ/MES/M2K stand in as correlated index-breakout proxies and **no claim about Nikkei
specifically is supported by these results.** Wiring a Nikkei feed is a separate data task,
not a strategy task.

---

## 8. Provenance

- Critique target: ChatGPT reconstruction of breakouttradingacademy.com "Simple Nikkei
  Breakout Strategy".
- Discipline: `.claude/rules/ml-pitfalls-defense.md` (López de Prado / Aronson / Masters),
  `.claude/rules/testing.md` (point-in-time / no look-ahead), `jarvis-search-discipline`.
- Reused code: `breakout_signals.py`, `backtester.py`, `permutation_test.py`,
  `deflated_sharpe.py`, `contract_specs.py`, `run_mcpt.py` (extended, not duplicated).
