# Funnel Tier Thresholds — Calibrated for "Moderately Aggressive"

These are the gate thresholds applied by `scripts/funnel_gate.py`. Each is calibrated to the explicit goal: **maximize realized profitability while keeping the probability of overfit-driven failure manageable**.

These are NOT placeholders. They were chosen with specific reasoning. If you change them, document why in a git commit message — silent threshold drift is how funnels turn into rubber stamps.

## Tier Definitions

| Tier | What it means | What happens next |
|---|---|---|
| **A** | Paper trade candidate — all gates pass | Goes to `engine/backtest/live_promotion_gate.py`, then paper trading |
| **B** | Watch list — fails ≤ 2 gates but DSR ≥ 1.0 | Documented improvement hypotheses generated, retest in 4 weeks |
| **C** | Killed | Documented in kill_list.md with reason, do not re-pitch without new evidence |

## The Gates (Tier A requires ALL pass)

### Gate 1 — Deflated Sharpe Ratio ≥ 0.80

**What:** DSR from `engine/backtest/deflated_sharpe.py`, computed using:
- N = total number of trials run on this strategy family (includes parameter sensitivity, regime tests, MTF tests)
- T = number of trading days in OOS sample
- Strategy returns' actual skew/kurtosis

**Why 0.80:**
- Conservative camp: 0.95 (Lopez de Prado's textbook recommendation for "publishable" results)
- Aggressive camp: 0.50 (basically a coin flip)
- 0.80 = ~80% probability that observed Sharpe reflects real edge, not selection bias
- For a 24-month ES dataset with realistic trial counts (~50–200 per strategy family), 0.80 corresponds to observed Sharpe ≈ 1.2–1.6 — achievable for real strategies, unachievable for noise

### Gate 2 — Probability of Backtest Overfit (PBO) < 0.40

**What:** PBO via Bailey/Lopez de Prado method using combinatorial fold rankings. Computed in `funnel_gate.py` using outputs from `engine/backtest/cpcv.py`.

**Why 0.40:**
- LdP default: 0.50 (better-than-coin-flip threshold)
- Tightening to 0.40 because we're an aggressive selector — we'd rather kill a marginal strategy than promote noise
- PBO ≥ 0.50 is unacceptable in any case (more likely overfit than not)

### Gate 3 — Profit Factor 95% CI Lower Bound > 1.15

**What:** Bootstrap 95% CI on profit factor from `engine/backtest/monte_carlo.py`. Take the lower bound (P2.5 percentile).

**Why 1.15:**
- 1.00 = breakeven possible in unlucky world → unacceptable
- 1.10 = standard minimum for "real but marginal"
- 1.15 = our floor; means even the 2.5th percentile bootstrap world is making money after costs
- Tighter than typical because ES costs (commission + slippage) eat ~$5–8/RT; we need cushion

### Gate 4 — OOS/IS Sharpe Degradation < 40%

**What:** `1 - (Sharpe_OOS / Sharpe_IS)`. If IS Sharpe 2.0 and OOS Sharpe 1.4, degradation = 30%, passes.

**Why 40%:**
- Some degradation is normal and expected (50% is the "anything goes" benchmark)
- 40% is tight — strategies that hold up well across the IS/OOS boundary are systematically more likely to survive in production
- Degradation > 40% almost always means parameter overfit

### Gate 5 — Minimum OOS Trades ≥ 40

**What:** Count of OOS trades across all WFO folds combined.

**Why 40:**
- Statistical power: < 30 trades makes Sharpe confidence intervals essentially useless
- 40 trades over 24 months OOS = ~1.7 trades/month — minimum viable for any non-position-trading strategy
- Strategies that don't generate this much activity are either (a) too rare to backtest reliably or (b) actually a position-trading strategy that needs a different framework

### Gate 6 — Regime Breadth: ≥ 2 of 4 vol regimes OR ≥ 1 regime with DSR ≥ 1.2

**What:** Vol regimes from `engine/analytics/vix_overlay.py` or `vix_percentile_regime.py`:
- Low vol (VIX < 15)
- Normal vol (15 ≤ VIX < 20)
- Elevated vol (20 ≤ VIX < 30)
- High vol (VIX ≥ 30)

**Why this rule:**
- Pure "must work in all regimes" is too restrictive — kills good specialists
- Pure "works in any regime" is too permissive — overfits to a single regime
- The OR clause allows a single-regime "specialist" if it's *very* good (DSR ≥ 1.2) in that regime, because we can then gate live execution on regime detection
- 2-regime requirement for generalists prevents calling a strategy "robust" when it only works in one market mood

### Gate 7 — Max Drawdown to Average Trade Ratio < 25×

**What:** `max_drawdown / avg_trade_pnl`

**Why 25×:**
- Catches strategies where one bad period eats 25+ average trades' worth of gains
- These almost always have hidden tail risk (regime change, gap risk, correlation breakdown)
- 25 is moderately aggressive — strict camp uses 15, but that kills legitimate breakout strategies

### Gate 8 — Slippage Stress: DSR ≥ 0.50 at 2× assumed slippage

**What:** Re-run backtest with 2× the slippage assumption. Pass if DSR still ≥ 0.50.

**Why:**
- ES slippage on 5m signals in volatile markets is brutal — 1 tick assumption often understates reality
- Strategies that die at 2× slippage are fragile to execution quality
- 0.50 floor (not 0.80 like Gate 1) because we're testing the stressed scenario — we want survival, not flourishing

### Gate 9 — Permutation Test p-value < 0.05

**What:** Bar permutation test via `engine/backtest/bar_permute.py` + `engine/analytics/permutation_test.py`. Shuffle the returns and re-run. If the strategy still finds edge on shuffled data, the edge is fake.

**Why p < 0.05:**
- Standard statistical significance threshold
- Permutation test is the cleanest test of "is this real or am I curve-fitting to specific bar sequences"
- Many "passing" backtests fail this gate — it's a common kill reason and that's GOOD

### Gate 10 — Bar Contamination Check (Inherited from `bars_repository.py`)

**What:** Verify the bars used in the backtest don't contain the sentinel-100.5 contamination pattern or other flagged anomalies from the 2026-06 incident.

**Why:**
- Real edges have been faked in this repo before by bad-tick contamination
- This is a non-negotiable hygiene check; failure = kill regardless of other metrics

## Tier B (Watch List) Rules

A strategy is Tier B if:
- It fails ≤ 2 Tier A gates
- AND DSR ≥ 1.0 (lower bar than Tier A's 0.80, but the spirit is: it's clearly real, just needs work)
- AND none of the failed gates are Gate 9 (permutation) or Gate 10 (contamination)

For each Tier B strategy, `funnel_gate.py` generates 2–3 specific improvement hypotheses based on which gates failed. Examples:

- **Fails Gate 4 (degradation):** "Reduce parameter count from 6 to 4 by replacing X and Y with fixed values"
- **Fails Gate 6 (regime):** "Add regime filter — only trade when VIX percentile in observed-edge band"
- **Fails Gate 3 (PF CI):** "Tighten stop-loss to improve risk/reward; current SL is 2× ATR, try 1.5× ATR"

## Tier C (Killed) Rules

Anything else is Tier C. The kill reason is logged with which gates failed and the corresponding gate values. This is critical:

**A documented kill is a permanent kill** (until new evidence). The `kill_list.md` exists so you don't re-pitch a strategy idea in 6 months that already failed for reason X.

## When to Override

Manual override is allowed in two cases ONLY:

1. **You've found a methodology bug in the gate logic.** Fix the bug, recompute everything, document the recalculation in `funnel_gate.py` changelog.

2. **The strategy has fundamental properties that the gates don't capture.** Example: a tail-risk hedge that loses money 90% of the time but pays off enormously in crashes — Gate 5 (min trades) and Gate 3 (PF CI) will both fail, but the strategy is still valuable for portfolio purposes. Document the override reason in `verdict.json` with `manual_override: true` and a written justification.

Never override "because it feels right" or "because the author is famous." That's how rubber stamping starts.

## Threshold Calibration History

| Date | Change | Reason |
|---|---|---|
| 2026-06-26 | Initial calibration | Matt requested moderately aggressive + max profitability |

Append every future threshold change to this table.
