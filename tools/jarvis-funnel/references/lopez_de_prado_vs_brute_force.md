# Lopez de Prado Robust Testing vs. Brute Force — Why the Funnel Wins

This doc exists to settle the methodology argument once. Read it before second-guessing why we don't just "test every combination."

## The Brute Force Pitch (and why it sounds reasonable)

The intuitive argument: "I have compute. I have data. Why not test every strategy × instrument × timeframe × parameter combination, then pick the winners?"

For Jarvis-Trader's scope (just to set the floor on cost):
- Strategies: ~80 (60 inventoried + 20 variations)
- Instruments: 9 (ES, NQ, GC, ZC, CL, SPY options, TSLA, VIX, VXX)
- Timeframes: 3 (5m, 30m, 1h)
- Parameter sweeps: 4 params × 5 values = 625 variants per strategy
- WFO folds: 10
- Pairwise combinations: C(80,2) = 3,160
- Triple combinations: C(80,3) = 82,160

**Total naive backtest count: ~8.4M single tests + ~1.25B combination tests ≈ 1.26 billion backtests.**

Even if each ran in 50ms (optimistic for vectorized), that's **~2 years of single-core compute**, or about 11 days on a 64-core box. Token cost if orchestrated via LLM agents: catastrophic.

That's not the real problem.

## The Real Problem: Multiple Testing Makes "Winners" Statistically Meaningless

When you run N independent backtests, the **expected maximum Sharpe** by pure luck — even if every strategy has zero true edge — grows with N.

### The Math (Bailey & Lopez de Prado, 2014)

For N independent backtests with true Sharpe = 0:

```
E[max Sharpe] ≈ √(2 · ln(N)) · σ_SR
```

Where `σ_SR` is the standard deviation of estimated Sharpe (≈ √(1/T) for T years of data on Gaussian-ish returns).

With T = 2 years (your ES data):
- N = 100 trials → E[max Sharpe] ≈ √(2·ln(100)) · √(1/2) ≈ **2.15** by luck alone
- N = 10,000 trials → E[max Sharpe] ≈ √(2·ln(10000)) · √(1/2) ≈ **3.03** by luck alone
- N = 1,000,000 trials → E[max Sharpe] ≈ **3.71** by luck alone

**Translation: at 1M+ tests, you should expect to find a "Sharpe 3.7" strategy that has literally zero true edge.** It will look amazing in backtest and lose money the moment you live-trade it.

This isn't theory. It's the dominant reason 90%+ of "discovered" trading strategies fail in production.

Source: [Bailey, D.H. and López de Prado, M. (2014). "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality." Journal of Portfolio Management.](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551)

## The Deflated Sharpe Ratio (DSR) — The Antidote

DSR corrects the observed Sharpe by deflating it based on:
1. **N** — number of trials run on this strategy family
2. **T** — sample size (number of returns)
3. **γ_3, γ_4** — skew and kurtosis of strategy returns (non-normality penalty)
4. **σ_SR** — standard deviation of Sharpe across the N trials

The formula (simplified):

```
DSR = Φ( (SR_observed - E[max SR | null]) · √(T-1) / √(1 - γ_3·SR_observed + (γ_4-1)/4 · SR_observed²) )
```

Where Φ is the standard normal CDF. DSR returns a probability — "what's the chance this Sharpe is real given how many things I tried?"

**Practical interpretation:**
- DSR > 0.95 → strong evidence of real edge
- DSR 0.8–0.95 → likely real but watch closely
- DSR 0.5–0.8 → coin flip, kill or improve
- DSR < 0.5 → almost certainly noise

Your repo already has `engine/backtest/deflated_sharpe.py`. Use it.

## The Funnel Approach (What This Skill Does)

Instead of running 1.26B tests, the funnel runs a much smaller targeted battery designed around **hypothesis-first testing**:

### Stage 1: Hypothesis Filter (free)
Every strategy must have a stated `economic_rationale`. No rationale → killed before any backtest.
**Impact: kills ~30–40% of candidates at zero compute cost.**

### Stage 2: Single-Path Smoke Test (cheap)
1 instrument, 1 timeframe (the one the rationale supports), author defaults, no parameter sweep.
**Impact: ~50% kill rate. Compute: ~30 backtests total.**

### Stage 3: Robustness Battery (moderate)
Full LdP battery on survivors only:
- Walk-forward (~10 folds)
- CPCV (~15 paths)
- Deflated Sharpe (uses #trials counter from earlier stages)
- PBO via combinatorial fold combinations
- Monte Carlo (10k bootstrap resamples — cheap, vectorized)
- Bar permutation test
- Regime conditioning
**Impact: ~10–15 backtests × ~50 robustness paths = ~500–750 tests per survivor. Across 15 survivors: ~10,000 tests total.**

### Stage 4: Combinations (small, targeted)
Only Tier A survivors. Only low-correlation pairs/triples.
**Impact: ~50–200 combination tests.**

**Total funnel compute: ~10,500–11,000 tests vs. 1.26B naive = 99.999% reduction with HIGHER statistical confidence.**

## Why "Higher Statistical Confidence" — A Concrete Example

Imagine two scenarios both ending with a strategy showing live Sharpe 1.5:

### Scenario A: Brute Force
- Ran 1,000,000 backtests
- Picked the top-Sharpe one (observed 4.2)
- DSR for this finding ≈ 0.31 → likely noise
- In production: degrades to 0.3 in first 6 months, then loses money

### Scenario B: Funnel
- Ran 80 hypothesis-driven candidates (Phase 2)
- 15 survived to Phase 3, full robustness battery
- 4 survived to Tier A
- Top strategy has observed Sharpe 1.8, DSR 0.91, PBO 0.18, OOS/IS Sharpe ratio 0.78, works in 3 of 4 vol regimes
- In production: degrades to ~1.4–1.6 (normal degradation), stays profitable

**Same observed Sharpe at the end of testing. Wildly different outcomes in production.**

The difference is the funnel's selection process is statistically defensible. The brute force's isn't.

## What About "But I Want Maximum Coverage"?

The funnel gives you MORE coverage of the hypothesis space, not less, because:

1. **Brute force gets stuck testing trivial parameter variations** (RSI 14 vs RSI 15 vs RSI 16). Most of its tests are near-duplicates.
2. **The funnel forces you to articulate WHY each strategy might work** — which surfaces new hypotheses you wouldn't have thought to brute-force.
3. **The funnel's Phase 1 inventory uses LLM agents to extract every hypothesis** from repo code, bookmarks, articles, and TOS scripts — *that's* where coverage comes from, not from parameter sweeps.
4. **Phase 3 parameter sensitivity is bounded** — instead of testing every value, we test the author's default ± 25%, ± 50% to confirm the strategy isn't a single-magic-value fluke. That's enough to detect overfit without combinatorial blowup.

## What If a Brute Force Finding Looks Real?

Sometimes brute force surfaces a real strategy that the funnel might miss. Two safeguards:

1. **Anything from brute force runs through the funnel before getting Tier A.** No exceptions. If it survives DSR, PBO, CPCV, regime, permutation — fine, it's real.
2. **Strategy_lab/strategy_generator.py and discovery_loop.py in your repo can still do exploratory generation.** They're a hypothesis source that feeds Phase 1, not a parallel test path. That's the right architecture.

## The Bottom Line

Brute force optimizes for test count. The funnel optimizes for **production-survivable edges**. They are not the same goal, and the difference shows up the moment real money is on the line.

This skill enforces the funnel. If you ever feel the urge to "just run all the combos to see what happens," re-read this doc, then check `engine/backtest/run_*.py` — the 80 `run_*` scripts already in the repo are mostly partial brute-force runs whose results live in `engine/data/mgc_wfo_journal.csv` and the gate_v2 verdict logs. Look at how many got FAIL verdicts. That's the brute force tax.

## Further Reading

- López de Prado, M. (2018). *Advances in Financial Machine Learning.* Wiley. Especially Ch. 7 (CPCV), Ch. 11 (Backtest Statistics), Ch. 12 (Backtest Overfitting).
- Bailey, D.H., Borwein, J.M., López de Prado, M., Zhu, Q.J. (2017). "The Probability of Backtest Overfitting." [Journal of Computational Finance.](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253)
- Harvey, C.R., Liu, Y. (2015). "Backtesting." [Journal of Portfolio Management.](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2345489)
