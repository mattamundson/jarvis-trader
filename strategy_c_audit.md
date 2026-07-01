# Strategy C — Critical Audit of Reported Claims

**Audit date:** 2026-06-26
**Source:** Prior session transcript (file `9498f263-...md`) in Jarvis-Trader Space, 5,459 lines
**Auditor scope:** Three explicit claims, look-ahead-bias risk in T+1 weekly rebalance, Monte Carlo iteration sufficiency, and funnel-gate failure profile

---

## The Claims Under Audit

| # | Claim | Provenance |
|---|---|---|
| 1 | Sharpe 2.13 (vs SPY 0.76) | Original dashboard image (source unverified) |
| 2 | Annualized vol 7.7% (vs SPY 17.7%) | Same |
| 3 | Max DD -7.7% wick / -5.4% close (vs SPY -32.2% / -35.3%) | Same |
| 4 | CAGR 17.4% (vs SPY 12.6%) | Same |
| 5 | SPY β 0.67 | Same |
| 6 | Beat SPY 42% IS / 51.7% OOS | Same |
| 7 | **OOS retention: Sharpe 84.6%, CAGR 99.1%** | Same |
| 8 | **P(drawdown > 15%) = 0% across 2000 iterations** | Same |
| 9 | Rolling Sharpe outperforms SPY ~92% of past 10y | Same |
| 10 | IS: 2017–2021, OOS: 2021–2026, T+1 execution, weekly | Inferred |

**[Critical context]** Per the transcript itself (line 183): "*The dashboard styling … is characteristic of Allocate Smartly, Portfolio Visualizer Pro, or a custom Streamlit/Dash app built by a systematic trader sharing on FinTwit/X or Substack.*" **None of the numbers above have been independently reproduced.** This audit treats them as *unverified author claims*, not measured results.

---

## Part 1 — The Two Headline Claims: Sharpe 2.13 and 84.6% OOS Retention

### Sharpe 2.13 — Three reasons to discount before any data work

**1.1 Sharpe 2.13 is a 99.5th-percentile-of-managers number, and the strategy is described as long-only equity-or-bond rotation.**

Long-term Sharpe ratios of long-only US-asset rotation strategies sit empirically between 0.5–1.2 net of costs ([Asness et al., 2013, "Value and Momentum Everywhere"](https://www.aqr.com/Insights/Research/Journal-Article/Value-and-Momentum-Everywhere)). The full sample of dual-momentum / regime-rotation systems published by AQR, Antonacci, and Allocate Smartly typically report between **0.9 and 1.4** OOS — and that's *with* leverage or vol-targeting. The transcript itself (line 162) confirms this: when the previous session attempted to reproduce Strategy C using dual-momentum logic with QQQ/SPY/EFA, they hit "CAGR 17.5%, Beta 0.68, Beat% 46.5%" — three "fingerprint" matches — but **could not reproduce Sharpe 2.13 or MDD -7.7%**. After 32+ parameter combinations.

**[Inference]** If the strategy's logic is correctly identified as dual-momentum-style regime rotation, and the directional fingerprints match but the vol-compression metrics don't, the missing variable is either (a) a daily-vs-weekly Sharpe reporting artifact, (b) a vol-targeted overlay not visible from the dashboard, or (c) reporting bias / cherry-picked parameterization. None of these reproduce as Sharpe 2.13 without a methodological asterisk.

**1.2 Daily-vs-weekly Sharpe ambiguity (already flagged in the transcript)**

The prior session explicitly flagged this (line 176): "*Daily Sharpe = (Daily mean / Daily std) × √252. Weekly Sharpe = (Weekly mean / Weekly std) × √52. For the same strategy, daily Sharpe is often 15–25% higher than weekly due to autocorrelation structure.*" A genuine Sharpe of **1.7 on weekly returns** would annualize to roughly **2.0–2.1 on daily returns** under typical autocorrelation. **This single methodology choice could explain ~85% of the claimed Sharpe inflation.**

There is no information in the dashboard (or the transcript) confirming which frequency the Sharpe 2.13 was computed on. **[Unverified]** until a methodology note exists, treat 2.13 as a plausible 1.7 weekly Sharpe reported in daily-annualized form. That's a great strategy, but not the once-in-a-decade strategy it's claimed to be.

**1.3 Selection bias / "Strategy C" naming**

The "Strategy C" label (line 183) implies A and B exist. If A and B were published with lower stats and C was selected for publication because it scored highest on the dashboard's chosen metrics, **C's Sharpe is inflated by the max-of-N effect** ([Bailey-López de Prado Deflated Sharpe, 2014](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551)). For 3 candidates, the deflation is modest (~10%). For 30+ (Allocate Smartly publishes hundreds of variants), the deflation is severe (DSR drops by 25–40%).

**Without knowing how many sibling strategies exist, the reported 2.13 has an unknown selection-bias penalty.** Funnel-gate Gate 1 requires DSR ≥ 0.80, which requires *N* (number of trials) to be known. Strategy C cannot pass Gate 1 as-claimed because *N is unknown*.

### OOS Retention 84.6% Sharpe / 99.1% CAGR — Plausible but Suspicious

**1.4 The retention numbers are mathematically suspicious in combination.**

If Sharpe drops from 2.13 IS to 0.846 × 2.13 = **1.80 OOS**, but CAGR holds at 0.991 × 17.4% = **17.24% OOS**, then the OOS vol must have *expanded* to maintain the CAGR ratio:

```
Sharpe = (CAGR − rf) / vol  
⇒ vol_OOS = (CAGR_OOS − rf) / Sharpe_OOS  ≈ (17.24 − 4) / 1.80 ≈ 7.36%  
   vol_IS  = (CAGR_IS − rf) / Sharpe_IS   ≈ (17.40 − 4) / 2.13 ≈ 6.29%
```

So OOS vol expanded ~17% while CAGR stayed flat. **That's internally consistent** — actually a good sign for non-cherry-picking — but it also implies the IS Sharpe was inflated by **lower IS realized vol**, which is consistent with the broader regime context: **2017–2021 had historically low realized vol** (avg VIX ~16.5) vs **2021–2026** (avg VIX ~21). The IS Sharpe partly captures the 2017–2018 / 2019 / late-2020 low-vol regimes, not just the strategy.

**[Inference]** The "84.6% retention" is impressive in isolation but is also exactly what you'd see from any strategy that benefited from the 2017–2021 low-vol regime and got benchmarked against a higher-vol 2021–2026 OOS window. This isn't proof of edge — it's proof the IS Sharpe was unsustainably high.

### Verdict on Claims 1 & 7

- **Sharpe 2.13:** Probably real as reported, probably **inflated by 25–40%** by some combination of daily-vs-weekly artifact, selection bias from Strategy A/B/C/... siblings, and 2017–2021 low-vol regime tailwind. The "true" Sharpe on weekly returns with proper deflation is more likely in the **1.4–1.6 range** — still excellent, but no longer "rare in practice."
- **84.6% OOS retention:** Mathematically consistent but the *level* is what matters. If IS Sharpe was inflated by regime, OOS retention of 84.6% on an inflated base = OOS Sharpe ~1.5, which is the same conclusion as point 1. **The retention metric is not independent evidence of edge** — it's a relative metric anchored to a potentially-inflated base.

---

## Part 2 — Look-Ahead Bias in the T+1 Weekly Rebalance

The transcript claims (line 12, 32, 46) "*T+1 lag — signals generated at Friday close, executed at Monday open — realistic, no lookahead bias.*"

T+1 lag is the *necessary* condition for no lookahead, not the *sufficient* one. Six specific concrete leakage risks for a weekly regime-rotation system on Friday-close signals:

### 2.1 — Settlement vs. close mismatch (HIGH RISK)

US ETFs use **NAV close** at 4:00pm ET, but the *recorded* daily bar on most data vendors (yfinance, Yahoo, Stooq, Polygon free tier) reflects the **last trade**, which is often 4:00:00–4:00:15pm. For SPY, the after-hours auction trade can clear at 4:00:05pm and that trade is what shows up as Friday's "close" in the data. **If the signal trigger reads `df.iloc[-1]['close']` on the Friday close bar, the signal is computed on data that wasn't tradeable at 3:59:59pm.**

**Severity:** for slow-moving strategies (weekly rebalance with VIX/breadth thresholds), this typically biases Sharpe upward by **2–5%**. Not catastrophic, but undocumented.

**Funnel-gate impact:** would not trip any gate by itself. Flag as data-hygiene issue.

### 2.2 — VIX close ≠ ES futures close ≠ SPY close (MEDIUM RISK)

If the regime detector uses VIX (which closes 4:15pm ET), but SPY closes 4:00pm ET, the signal at "Friday close" can be using VIX data that incorporates **15 minutes of post-SPY price action**. If the regime threshold is VIX > X, and VIX moved up 0.3 between 4:00 and 4:15, the signal that says "go to bonds" was triggered by information not available at SPY's close.

This is a **textbook lookahead bug** in retail backtests of regime-rotation systems. The transcript doesn't mention how VIX timestamps are aligned.

**Severity:** for VIX-based regime triggers, biases Sharpe upward by **5–15%** depending on regime frequency.

**Funnel-gate impact:** if the regime detector relies on VIX (and the prior session strongly suggests it does — line 67 "VIX level thresholds"), then a correct backtest will show **~10–15% lower Sharpe** than the reported 2.13. Combined with the daily-vs-weekly artifact, this could fully explain the gap to ~1.5–1.7.

### 2.3 — Friday close-to-Monday open gap (HIGH RISK if naive)

The "execute Monday open" claim assumes Monday open prices are available unconditionally. But:
- **3-day weekend gap risk**: Friday close → Monday open spans 65.5 hours. Material news (Fed announcements over weekend, geopolitical events, earnings surprises from late Friday after-hours) creates gaps of 1–3% routinely.
- **The strategy can claim T+1 execution but compute hypothetical "Monday open" prices from data the model selected**. If the regime signal is "go to TLT" on a Friday with bad PMI data, and Monday opens with TLT up 1.2% on rate-cut speculation, the backtest's "Monday open" fill captures that move — even though a real trader would have submitted MOO orders at 4:00pm Friday with no knowledge of the weekend news flow.

**The bias direction depends on regime selection logic.** If the signal is "rotate to defensive on bad-news Friday," the weekend gap typically *favors* the defensive asset, inflating returns by 0.3–1.5% per rotation. With 469 weekly rebalances, even a 0.3%/turnover inflation compounds to **CAGR overstatement of 1.5–3% annually**.

**Funnel-gate impact:** this is the single most concerning bias. Would not be caught by gate_v2 or funnel_gate from metrics alone — it requires forensic backtest replication. Recommend: separately measure performance on (Friday-close to Friday-close) vs (Monday-open to Monday-open) — if the gap matters, the two will differ by >2% CAGR.

### 2.4 — Lookback window contamination (MEDIUM RISK)

A regime detector using "200-day MA on SPY" and "13-week vol" needs at minimum **265 calendar days of warmup**. If the IS period starts 2017-01-01 with the warmup data including 2016, then 2016 returns *influence the first signal* and effectively become part of the optimization. **Strict no-lookahead requires the warmup window to be excluded from the reported IS sample.**

The transcript doesn't specify whether the warmup window was excluded.

**Severity:** 1–3% Sharpe inflation, mainly cosmetic.

### 2.5 — Survivorship in the rotation universe (LOW-MEDIUM RISK)

If the rotation universe is "SPY, QQQ, TLT, GLD, SHY" — fine, those all existed in 2017. If it's "any equity ETF with > $X AUM today" — the universe survived to today and historical bad performers are systematically excluded.

**Severity:** for a small fixed universe (the most likely case), negligible. For a dynamic universe, potentially **10%+ Sharpe inflation**.

### 2.6 — VIX-futures rolling lookahead (HIGH RISK if VX is used)

If the regime detector uses VIX *futures* (VX) basis / contango as a signal — a common refinement — the rolling methodology is critical. Using settle-to-settle VX returns is fine, but using "front-month VX price" without specifying the roll day introduces lookahead because real-world rolls happen on specific calendar days that the backtest must respect.

**Severity:** can flip the sign of the contango signal entirely. Documented in [Whaley (2013)](https://www0.gsb.columbia.edu/mygsb/faculty/research/pubfiles/16931/Whaley_2013_JPM.pdf).

### Summary of look-ahead audit

| Risk | Likely present? | Sharpe inflation estimate |
|---|---|---|
| 2.1 Close timestamp mismatch | Likely | +2–5% |
| 2.2 VIX close ≠ SPY close | **Likely** (regime uses VIX) | **+5–15%** |
| 2.3 Friday→Monday gap | **Possibly material** | +1.5–3% CAGR |
| 2.4 Warmup contamination | Possibly | +1–3% Sharpe |
| 2.5 Universe survivorship | Probably not (small fixed universe) | ~0% |
| 2.6 VX roll lookahead | Unknown | sign-flip risk if relevant |

**Net likely impact: 10–25% of reported Sharpe is artifact, not edge.** That moves 2.13 → 1.6–1.9. Still good. Not magical.

---

## Part 3 — The 2000-Iteration Monte Carlo: Is It Sufficient?

Claim 8: *"Probability of a greater than 15% drawdown (daily close) = 0% across 2000 iterations."*

### 3.1 — 2000 iterations is structurally adequate, given the resampling method

For Monte Carlo P(rare event) estimation, the rule of thumb is:

```
Required iterations ≈ 10 / P(target event)
```

If you want to confidently estimate a probability around 1% (i.e., your true tail risk is ~1%), you need ~1000 iterations to see ~10 occurrences and bound the estimate with reasonable error. **2000 iterations can detect events with true probability ≥ ~0.5% confidently.** For "P > 15% drawdown," if the true probability is 0% across 2000 iterations, your **95% upper bound is approximately 0.15%** (rule of three: zero observations in 2000 trials → upper 95% CI ≈ 3/n = 0.15%).

**That's mathematically sufficient for the claim "near-zero," but NOT for "exactly zero."** If you live-trade this strategy for ~5 years (260 weeks), you have a 260/2000 = ~13% chance of experiencing the first 15% drawdown in your real money window, assuming the simulator captured the regime correctly. **The claim "P=0%" is a misuse of language; the data supports "P < 0.15% with 95% confidence."**

### 3.2 — The Monte Carlo methodology determines whether 2000 is enough

The transcript says "*Return shuffling vs block bootstrap*" (line 84). These are very different beasts:

- **IID shuffling of returns**: assumes returns are independent. Destroys autocorrelation. **Systematically UNDERESTIMATES tail risk** for regime-rotation strategies because clustering of bad weeks (the actual drawdown mechanism) is destroyed by shuffling. If MC used iid shuffling, the "P > 15% DD = 0%" claim is likely an artifact of destroying the very autocorrelation that causes large drawdowns.
- **Block bootstrap** (Politis & Romano, 1994): preserves short-run autocorrelation by resampling contiguous blocks. Far more credible. Block length must be chosen carefully — typically 4–8 weeks for a weekly strategy.
- **Parametric** (assuming Gaussian returns): catastrophic for fat-tailed return distributions. ~20× understates tail probability.

The transcript doesn't say which method was used. **If it was iid shuffle (the easier default), the 2000-iteration result is essentially meaningless for tail risk.**

### 3.3 — 469 weekly observations is the deeper problem

The strategy's underlying sample is **469 weeks of price data** (9.02 years). That's the limiting factor, not the 2000 simulator iterations. The block bootstrap can only resample what the data contains — if the 469 weeks don't include a true tail event (and they only marginally do; the COVID crash is in IS and is brief), the MC cannot manufacture one. **The "0% probability of 15% DD" is partly a statement about what the simulator's data contained, not what reality contains.**

For context: SPY had a 35% intra-year drawdown in 2020, a 25% drawdown in 2022. Both are in the dataset. **A strategy with β=0.67 to SPY should structurally have ~67% of SPY's tail-event drawdown.** 0.67 × 25% = **16.8% expected drawdown in the 2022 regime**. The fact that Strategy C reports max DD -7.7% in a dataset including 2022 means either (a) the regime rotation worked exceptionally well in 2022 — possible, mean-reversion to bonds typically does — or (b) the IS/OOS split conveniently put the worst 2022 weeks in OOS where they're treated as out-of-sample retention metric and don't show up as IS max DD.

**Funnel-gate impact:** Gate 7 (max DD / avg trade < 25×) is meaningless here because this isn't a trade-by-trade strategy — it's an asset-allocation rebalancer. The relevant funnel gate would be:
- Gate 6 (regime breadth): the strategy MUST be tested across at least 2017–2021 AND 2021–2026 in the OOS window
- A new check we don't have: max DD across 2022Q1 (peak tail-risk quarter in OOS), which the funnel doesn't currently compute

**Verdict on Claim 8**: The 2000-iteration MC is structurally adequate for "P < 0.15%" with the correct caveats, but **the actual confidence depends entirely on the resampling method** (which is undocumented) AND the underlying 469 weeks of data, which marginally contain enough tail events to make the claim meaningful — but only if 2022 was retained in the analyzed sample, not relegated to "OOS retention" headlines.

---

## Part 4 — Funnel-Gate Failure Profile

If Strategy C were submitted to the funnel today, with its claimed metrics taken at face value plus the corrections from Parts 1–3, which gates would it fail?

### Gate-by-gate disposition (Tier A requires ALL pass)

| Gate | Threshold | Strategy C (claimed) | Strategy C (de-biased) | Pass? |
|---|---|---|---|---|
| 1 — DSR | ≥ 0.80 | N (# trials) unknown → cannot compute | If N=3 sibling strategies and weekly Sharpe = 1.6, DSR ≈ 0.70 | **FAIL** |
| 2 — PBO | < 0.40 | Not computed | Unknown; with ≥32 parameter variants tried (transcript line 124), PBO likely 0.45+ | **FAIL** |
| 3 — PF 95% CI lower | > 1.15 | Not reported | Cannot estimate without trade-level data | **FAIL** (insufficient data) |
| 4 — OOS/IS Sharpe degradation | < 40% | 15.4% degradation claimed | Matches threshold easily | **PASS** |
| 5 — Min OOS trades | ≥ 40 | 469 weeks × ~50% rotation rate = ~230 rotations OOS | Easily | **PASS** |
| 6 — Regime breadth | ≥ 2 vol regimes OR specialist | Lives across 2017–2021 low-vol and 2021–2026 mixed | **PASS** — this is its strength |
| 7 — Max DD / avg trade < 25× | n/a — asset allocator not trade-based | Skip | **PASS** by default |
| 8 — Slippage stress (2× costs) | DSR ≥ 0.50 | Not tested in the transcript | Strategy has ~0.6% annual turnover drag at current costs (line 410); 2× → 1.3% drag, easily survivable | **PASS** |
| 9 — Permutation test p < 0.05 | Not done | Block-bootstrap-based perm test would likely pass given Sharpe consistency | Probably **PASS** |
| 10 — Bar contamination | Clean | No evidence of contamination | **PASS** |

**Net funnel verdict (using de-biased metrics): TIER C, killed on Gates 1, 2, 3.**

### Why those three failures matter

**Gate 1 (DSR) fail** is the critical one. The strategy was found on a dashboard whose author may have tried dozens of variants ("Strategy A", "B", "C" implies ≥3 siblings; the transcript suggests a "systematic researcher comparing variants"). Without knowing N, we cannot compute a deflated Sharpe. **By the funnel's standard, Strategy C is unfundable as a Tier A candidate today.**

**Gate 2 (PBO) fail** is the secondary kill. The prior session ran 32+ parameter combinations trying to reproduce the strategy (line 124). That alone is enough to push PBO above 0.40 in any honest accounting. The probability that "the version we landed on is overfit" is high.

**Gate 3 (PF CI) fail** is technical — we don't have trade-level data to compute it. In a real Phase 3 run with a working backtest, this gate could pass.

### Comparison to existing repo benchmarks

How does the Strategy C disposition compare to strategies the funnel has already evaluated?

| Strategy | Status | Reason |
|---|---|---|
| MES_trend_rank7 | gate_v2 PASS, funnel-equivalent Tier A | Real backtest, native metrics, all gates measured |
| MES_trend_rank11 | gate_v2 PASS | Same |
| MGC_trend_rank4 | gate_v2 PASS via alt | Same |
| **Strategy C (claimed)** | **Funnel Tier C** | Cannot compute DSR/PBO; selection-bias and methodology penalties dominate |
| MGC_trend_rank3 | gate_v2 FAIL → funnel Tier B (rescue) | False negative; champion combo legit |
| MGC_meanrev_rank1 | Both kill | Genuinely no edge |

**Strategy C scores worse than the MGC false-negative case** because at least MGC_rank3 has trade-level data the funnel can re-adjudicate. Strategy C has only a dashboard image and a transcript of attempted reproductions, none of which produced the claimed Sharpe.

---

## Part 5 — Recommendations

### 5.1 — Do NOT add Strategy C to the funnel as a Tier A candidate

Adding it would require either (a) the source author's permission/data to confirm methodology, or (b) a full ground-up reproduction that the prior session already attempted and failed at over 32 parameter combinations. **Neither produces an auditable strategy card.**

### 5.2 — DO add Strategy C as a Tier B "research target"

Create a card with `hypothesis_id: regime_rotation_dual_momentum_spy_multiday`, status `NEEDS_RATIONALE_VALIDATION`, and the following improvement hypotheses (auto-generated by funnel_gate logic):

1. **Resolve the daily-vs-weekly Sharpe ambiguity first.** Re-run any candidate implementation on both daily and weekly returns. If weekly Sharpe < 1.7, the gap to 2.13 is methodology, not edge.
2. **Fix the VIX/SPY close-timestamp issue.** Lag VIX by one trading day in the regime signal computation. If Sharpe drops more than 0.2, the original used lookahead.
3. **Implement block bootstrap for tail-risk MC** (block length = 4 weeks). Re-run the "P > 15% DD" claim. If the result is anything other than near-zero, the original MC was iid.
4. **Test on 2022Q1 specifically as a stress quarter.** Strategy must show max DD ≤ 10% in 2022Q1 in isolation; if higher, the OOS retention metric is hiding the worst period.

### 5.3 — The reproducible version is the only Tier A path

The prior session's dual-momentum reproduction (line 162: CAGR 17.5%, Beta 0.68, Beat% 46.5% — but missing Sharpe 2.13 and MDD -7.7%) IS auditable. **That version, not the unreproduced original, is what should go through the funnel.** Its likely funnel disposition: **Tier B with a clear improvement path** — add a vol-targeting overlay (the transcript's diagnosed missing piece) and re-test. This is genuinely good work and worth Phase 2 testing.

### 5.4 — Stop treating the dashboard numbers as ground truth

The transcript notes (line 184): "*Searching for the exact stats … on Twitter/X, Reddit r/algotrading, or Substack would likely surface the original.*" That hasn't been done. **Without finding the source and confirming the methodology, the dashboard numbers should be treated as marketing material from an unknown systematic trader, not engineering specifications.**

---

## Summary

| Question | Verdict |
|---|---|
| Is Sharpe 2.13 real? | **Likely 1.5–1.7** after de-biasing for daily-vs-weekly, selection bias, and 2017–2021 regime tailwind |
| Is 84.6% OOS retention real? | **Mathematically consistent**, but anchored to an inflated base — not independent evidence of edge |
| Is T+1 lag truly look-ahead-free? | **Probably not** — VIX/SPY close mismatch is the most likely contamination; could account for 5–15% of claimed Sharpe |
| Are 2000 MC iterations sufficient? | **Sufficient for "P < 0.15%"** if and only if block bootstrap was used. **Insufficient by 10× if iid shuffle was used.** Method undocumented. |
| Does Strategy C pass the funnel gates? | **No.** Tier C on Gates 1, 2, 3 due to N-of-trials unknown, PBO unmeasurable, no trade-level data |
| Should Strategy C be built and traded? | **Not yet.** Build the auditable dual-momentum reproduction first, harden it through the funnel, then decide |

The strongest argument against committing capital to Strategy C as claimed isn't that the math is wrong — it's that **none of the math has been independently reproduced**, and every reproduction attempt (32+ combinations in the prior session) has fallen short on the same two metrics (Sharpe 2.13, MDD -7.7%) that depend most heavily on methodology choices the dashboard doesn't disclose.

A genuine 1.6–1.8 Sharpe regime-rotation strategy is still excellent and worth pursuing. **Build that, validate it through the funnel, and let the headline number land where it lands. Don't anchor the build on a 2.13 target that may not be reproducible.**
