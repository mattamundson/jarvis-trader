# Mean-Reversion Audit — Why Both Gates Reject Every Strategy

**Date:** 2026-06-26 · **Audit scope:** `meanrev_signals.py`, `mean_reversion_ou.py`, 5 runner files (MES r1, MES r2, MGC r1, MGC r2, MCL htf r1), 4 verdict files

---

## TL;DR

The mean-reversion failures are **not gate over-strictness**. The strategy logic has three structural problems that both gate_v2 and the funnel_gate would correctly catch, and the team has already iterated through hypotheses A–F on MCL trying to fix them. **The gates are working — the underlying mean-reversion thesis on these instruments is genuinely weak in the current regime.**

That said, there are two specific issues where the *implementation* is leaving edge on the table, and one place where the gate is asking the wrong question. Those are fixable.

---

## The actual numbers (MGC mean-rev rank1 — the cleanest case)

| Metric | Value | Threshold | What it means |
|---|---|---|---|
| p_edge | 0.32 | ≥ 0.95 | Only 32% of OOS windows showed PF > 1. **Worse than random direction.** |
| DSR | 0.0 | ≥ 0.30 | Sharpe deflates to zero after multi-trial correction. **No edge surviving the noise floor.** |
| pf_ci_lower | 0.72 | ≥ 1.10 | Even the bootstrap upper-tail says PF < 1. **Losing money in most resampled worlds.** |
| mc_95th_dd | 5.69% | ≤ 7% | Drawdown ok-ish. **Only metric that passes.** |
| WFO consistency | WEAK | MOD or STRONG | Strategy doesn't repeat across windows. |
| fixed_params_min_pf | 0.33 | ≥ 1.20 | Worst combo loses 67% of dollars in. |
| fixed_params_max_pf | **1.17** | (informational) | Best combo barely above breakeven. |
| OOS trades | 325 | (informational) | **Not a sample-size problem.** Plenty of trades. |

The strategy fired 325 times and the best parameter combination achieved PF=1.17. After costs and overfitting penalty, that's no edge. The remaining 8 of 9 combos lost money outright.

---

## Three structural failures driving the FAILs

### 1. **Static volatility triggers in a non-stationary vol regime**

The entry condition is `close < BB_lower (20-period, 2σ) AND RSI(14) < 30`. Both indicators are **adaptive in the lookback window** but assume **stationary distributions** within that window.

Problem: when MGC's realized volatility regime-shifts (which it did multiple times in the test period), the 2σ band stops being a "tail event" — it becomes the new normal. The strategy keeps firing at "extreme" dislocations that aren't extreme any more, and the reversion target (midband) is itself drifting away.

**Evidence in the data:** windows 4–10 of the rank1 WFO produced PFs of 0.13–0.51 during MGC's mid-2025 trending leg. The signal generator's docstring even concedes this (`run_mgc_meanrev_rank2.py`: *"During trending moves, BB-band breaches are not exhaustion — they're momentum extension"*).

**Fix:** replace the static 2σ trigger with a **volatility-adjusted percentile trigger** — fire when price is above the 95th percentile of close-to-band distance over a rolling 200-bar window. This automatically inflates the bar to clear during high-vol regimes. The rv_band gate (rank2) tries to do this from outside the signal, but it would be more effective baked into the trigger itself.

### 2. **Missing tail-risk control — fixed ATR stop in a non-stationary tail**

Stop is `entry ± 1.5 × ATR(14)`. ATR is also a 14-bar lookback. When the vol regime expands, the ATR catches up after the fact — but the stop placed on the entry bar uses pre-expansion ATR, so it's **systematically too tight** during the very regime where mean-rev fails worst.

**Concrete evidence:** the docstring of `meanrev_signals.py` notes "55% stop-hit rate" on the MCL first pass (`hyp-A`). For a strategy that's supposed to revert to a midband 1–2σ away with a 1.5σ stop, 55% stop-hits means the **risk/reward asymmetry is inverted** — you're stopping out on the trades the strategy was designed to win on.

**Fix options (any one would help, ideally all three):**
- **Volatility-targeted stop sizing:** scale stop by realized vol percentile, not raw ATR. `stop = entry ± max(1.5 × ATR_14, 1.0 × ATR_50_p75)` — wider stops in high-vol regimes.
- **Time-stop component:** if reversion hasn't started within N bars (e.g., 8 hours on 1h bars), exit at market regardless of stop. This caps the tail risk on positions that are simply wrong about regime.
- **Trail to midband:** once price moves halfway to target, trail the stop to breakeven. Reduces the "60% of win is given back" pattern.

### 3. **No tail-risk control on cluster events**

Mean-reversion losers cluster — when one trade fails, multiple consecutive trades typically fail (same regime, same direction). The current code has **no daily loss limit, no consecutive-loss circuit breaker, no portfolio-level kill switch**. Every trade is treated as independent.

**Evidence:** rank1 has 9 parameter combos with fixed_params_mean_pf = 0.83. If the variance across combos were uncorrelated bad luck, you'd see a wider spread; the tight clustering near 0.83 means the LOSSES are systemic across the parameter grid — same regime crushed all 9 variants simultaneously.

**Fix:** wrap entries with a **strategy-level circuit breaker**:
- Skip new entries if rolling 5-trade PnL < -2 × avg_winner
- Skip new entries if last 3 trades were all stops
- Hard daily loss cap of 1% of capital

This won't recover lost trades but it prevents the bad-regime cluster from compounding. Critical for live trading.

---

## Where the team has *already* tried to fix this

The MCL hypothesis ladder (A → F documented in `run_mcl_htf_meanrev_rank1.py`) is sophisticated work — they've tried sentiment overlays, RV bands, SMA trend filters, daily-RSI conditioning. **All variants failed** to clear the alt-path threshold. That's a strong signal the issue isn't the filter design — it's the trigger and exit mechanics, which haven't been refactored. Hypotheses A–F bolt filters onto a broken trigger; the trigger itself needs the fix.

Specifically, the **OU module (`mean_reversion_ou.py`) is the right idea and is mostly unused.** It estimates theta (reversion speed), mu (drift), sigma (vol) — exactly the parameters a properly-tuned mean-rev strategy needs. But none of the runner scripts use it; they all call `generate_bollinger_rsi_signals()` instead. The Bollinger+RSI signal is a *proxy* for OU mean-reversion that assumes a static mean — and that assumption is what's breaking. **Wiring the OU estimates back into entry/exit/sizing is probably the single highest-leverage fix.**

---

## Is gate_v2 (or funnel_gate) doing anything wrong here?

Mostly no. Two small calibration concerns:

1. **Both gates use `fixed_params_min_pf ≥ 1.20` as a hard alt-path floor.** Same issue identified in the MGC trend rank3 audit: this penalizes wide search grids. On the meanrev runs the grid is only 9 combos, so the effect is small — but `fixed_params_min_pf = 0.33` is so far below the threshold that the gates are right anyway. **Not a false negative.**

2. **`p_edge ≥ 0.95` may be too strict for *legitimate specialist* strategies** that only trade ~30% of the time but win when they do. A regime-gated mean-rev strategy could legitimately have p_edge of 0.6 (with 60% of windows being "regime not present, no trades or break-even") and still be a great Tier B candidate. The funnel_gate already handles this via the specialist-regime path in Gate 6 — but the gate_v2 alt path doesn't have an equivalent escape valve. **Worth flagging for the next gate calibration.**

---

## Recommendation for the funnel

When Phase 2/3 of the funnel reaches the mean-reversion family, **do not retest the current scripts as-is.** Instead, fork a `meanrev_v2` family with the three structural fixes above:

1. Vol-adjusted percentile triggers (replaces static 2σ Bollinger)
2. Vol-targeted stops + time-stop (replaces fixed 1.5×ATR)
3. Strategy-level circuit breaker on cluster losses

If `meanrev_v2` still fails the gate after these fixes, the conclusion is that mean-reversion has no edge on liquid micro futures in the post-2024 regime — file that as a documented dead-end and move on. **Hypothesis A–F-with-filters has been exhausted; iteration on triggers and risk controls is the remaining unexplored axis.**

Time estimate: 1–2 days of implementation, 1 day of WFO testing per instrument. Roughly the same effort as one more bolted-on filter, but addresses the actual mechanism rather than the symptom.
