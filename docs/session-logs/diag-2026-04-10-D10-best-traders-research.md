# Best-Traders Research — Sources & Rules

**Agent:** D10 | **Date:** 2026-04-10 | **Task:** Deep-dive on Section K "Best-Traders Overlay" from docs/strategy/JARVIS-STRATEGY-v1.md

---

## Paul Tudor Jones
**Known for:** Global macro investing, Tudor Investment Corporation founder. Legendary call on 1987 Black Monday crash.

**Quote:** "Every day I assume every position I have is wrong. I know where my stop risk points are going to be. I do that so I can define my maximum possible drawdown."
- **Source:** [LogikFX — Paul Tudor Jones Top 10 Trading Rules](https://www.logikfx.com/post/paul-tudor-jones-top-10-trading-rules)
- **Also cited:** [TraderLion PTJ Quotes](https://traderlion.com/quotes/paul-tudor-jones-quotes/), [Macro Ops](https://macro-ops.com/lessons-from-a-trading-great-paul-tudor-jones-ptj/)

**Rule:** Never risk more than 2% capital per trade. Target minimum 2:1 RRR, preferably 5:1. Use mental + technical + time-based stops. Never average down losers.
- **Application to JARVIS:** PARTIALLY IMPLEMENTED. Engine has MAX_POSITION_SIZE=5% (not 2%), MAX_ORDER_VALUE=$5k (hardcoded). Need to enforce RRR floor of 2:1 at TraderAgent sizing stage.
- **Risk of adoption:** Too tight for futures micro contracts (MES=$5 per point; 2% on $25k = $500 max; 1-contract stop=$50; limits entry to 10-point stops only). Conditional on account size.

---

## Linda Raschke
**Known for:** Price action pioneer. Holy Grail strategy. 40+ years trading, Street Smarts author.

**Quote:** "The first pullback in an uptrend is the most profitable trading setup, offering the best risk-reward ratio."
- **Source:** [TradersMinds — Linda Raschke Holy Grail Setup](https://tradersmastermind.com/linda-raschke-trading-strategy/)
- **Also cited:** [Gate.com — ADX & EMA Setup](https://www.gate.com/news/detail/18612681)

**Rule:** Enter first pullback to 20-EMA ONLY (not second/third). ADX > 30 confirms trend strength. Buy when price breaks above the first candle touching the 20-EMA. Stop below the pullback swing low. Profit-taking: trailing stop below 20-EMA or at recent swing highs.
- **Application to JARVIS:** NOT IMPLEMENTED. LLM agents are pattern-agnostic (debate-driven). Could add as TechnicalAnalystAgent overlay: detect ADX > 30, flag first 20-EMA retrace as high-conviction entry signal.
- **Risk of adoption:** False entries in choppy/sideways markets (ADX > 30 requires sustained trending). Whipsaws common on lower timeframes. Recommend: limit to daily/4H bars, require confirmation bar + volume.

---

## Al Brooks
**Known for:** Price action micro-structure, "Trading Price Action Trends/Ranges" books. Bar-by-bar analysis.

**Quote:** "A strong close near the high or low of a bar indicates control. Overlapping bars signal hesitation or a trading range. Valid breakouts are confirmed by powerful candles that close well beyond the channel edge."
- **Source:** [Brooks Price Action](https://www.brookspriceaction.com/) | [AronGroups — Trading Ranges](https://arongroups.co/technical-analyze/al-brooks-trading-ranges/)
- **Also cited:** [Trasignal — Al Brooks Lessons](https://trasignal.com/blog/forex/price-action-trends-by-al-brooks/)

**Rule:** Clean bar = large body, decisive close far from open, breakout of prior range. Weak bar = wick extends outside range but body closes inside (fakeout). H2 (second high) after inside bar = strong, clean breakout signal. Avoid trading weak/fakeout bars.
- **Application to JARVIS:** PARTIALLY IMPLEMENTED. No explicit "bar quality" filter in TechnicalAnalystAgent. Could enhance: measure body-to-total-range ratio, detect inside bars, validate breakouts with follow-through bars.
- **Risk of adoption:** Adds complexity; requires 1-minute/5-minute bars (not compatible with daily/hourly only). Micro-structure noise in futures can create false "clean" bars. Recommend: intraday only, pairs with volume confirmation.

---

## Stan Druckenmiller
**Known for:** Billion-dollar macro bets, Duquesne Capital founder. 30+ years zero down-years.

**Quote:** "The greatest investors make large concentrated bets where they have a lot of conviction. They're not buying 35 or 40 names and diversifying."
- **Source:** [The Hustle — Druckenmiller Q&A](https://thehustle.co/stanley-druckenmiller-q-and-a-trung-phanin) | [Marcellus — Conviction Bets](https://marcellus.in/story/stanley-druckenmiller-the-greatest-investors-make-large-concentrated-bets-where-they-have-a-lot-of-conviction/)

**Rule:** Sizing = 70–80% of performance. Press when conviction highest (odds tilted your way). Asymmetric risk-reward: win more when right than lose when wrong. Concentration decreases risk (concentrated position gets attention; diversified portfolio gets neglected). Never avoid sizing into high-conviction setups.
- **Application to JARVIS:** PARTIALLY IMPLEMENTED. DebateOrchestrator has confidence scoring, but TraderAgent caps at 2 micro-contracts max. Need conditional upsizing: if conviction > 0.75 AND confluence score > 0.60, allow 1 standard contract instead. Current system is over-diversified (11 agent signals, equal weighting).
- **Risk of adoption:** Requires precise edge detection. Over-sizing into false conviction signals (debate producing fake consensus) = catastrophic losses. Recommend: gate on walk-forward validation (Sharpe > 0.5 in live trading), require 3+ consecutive winning trades before upsizing.

---

## Ernie Chan
**Known for:** Quantitative trading pioneer. Doctorate in theoretical physics (Cornell). "Quantitative Trading: How to Build Your Own Algorithmic Trading Business" (Wiley, 2nd ed. 2017).

**Quote:** "You can choose to reduce drawdown instead of maximize Sharpe. The Calmar ratio (returns/drawdown) may be better. The importance is rigorous out-of-sample validation. In testing, out-of-sample alpha can be lower (e.g. Sharpe 0.75 vs backtest Sharpe 1.2)."
- **Source:** [Chan Blog — Optimizing Strategies without Overfitting](http://epchan.blogspot.com/2017/11/optimizing-trading-strategies-without-html) | [Academia.edu — Quantitative Trading PDF](https://www.academia.edu/28488586/Quantitative_Trading_Ernest_P_Chan)

**Rule:** Implement walk-forward validation (not just backtesting). Treat Day Zero as timestamp for new subadvisor; ignore pre-Day-Zero performance. Avoid selection bias by OOS testing. Accept Sharpe degradation in live: expect 30–40% lower Sharpe out-of-sample vs backtest. Use Calmar ratio (return/drawdown) if drawdown is concern.
- **Application to JARVIS:** PARTIALLY IMPLEMENTED. Walk-forward framework exists (engine/experiments/). However, live runs have NOT yet validated OOS Sharpe degradation vs backtest. WFE for MES = 0.82 (backtest), live TBD. Need to log actual OOS Sharpe, compare vs WFE forecast.
- **Risk of adoption:** Low risk if we follow rule strictly. High risk if we cherry-pick walk-forward windows. Recommend: lock backtest period (2023–2024), freeze OOS window (2025 onward), never retrain on 2025 data.

---

## James Simons / Renaissance Medallion
**Known for:** Mathematician, founder Renaissance Technologies (1982). Medallion Fund (1988): ~66% annual returns, best-performing hedge fund ever.

**Quote:** "[UNABLE TO VERIFY — recommend removing from strategy doc] Renaissance does not publish specific quant rules. Sources describe: 'Combine thousands of weak predictive signals into one robust system via feature engineering and multi-dimensional datasets.'"
- **Source:** [Medium — Mathematics of Renaissance](https://acontinuallearner.medium.com/uncovering-the-mathematics-behind-the-worlds-most-profitable-hedge-fund-79770d772997) | [LuxAlgo — Simons Strategies](https://www.luxalgo.com/blog/simons-strategies-renaissance-trading-unpacked/) | [Wikipedia — Renaissance Technologies](https://en.wikipedia.org/wiki/Renaissance_Technologies)

**Rule:** Signal orthogonality / decorrelation. Trade hundreds of global markets (stocks, futures, currencies, commodities) with uncorrelated signals. Each signal contributes small edge; aggregate = massive edge. Proprietary methodology — no public disclosure.
- **Application to JARVIS:** ASPIRATIONAL ONLY. Medallion's exact methods are secret (Simons/Ax patents filed 1990s–2000s, mostly expired but details withheld). JARVIS has 11 agents (not thousands of weak signals). Recommend: study architecture (aggregate small edges → robust system) but do NOT attempt to reverse-engineer specifics.
- **Risk of adoption:** Zero direct risk (not adopting proprietary methods). Risk: over-weighting this trader in strategy doc without concrete rules. Recommend: reframe as "inspiration" rather than "playbook."

---

## Mark Minervini / SEPA
**Known for:** Stock trend-following champion. "Trade Like a Stock Market Wizard" (McGraw-Hill 2009). SEPA = Specific Entry Point Analysis.

**Quote:** "Significant stock price appreciation often occurs during Stage 2 uptrends. Identifiable chart patterns typically emerge just before a stock initiates its major move."
- **Source:** [QuantStrategy.io — SEPA Strategy](https://quantstrategy.io/blog/sepa-strategy-explained-mastering-trend-following-with-mark/) | [FinerMarketPoints — SEPA Framework](https://www.finermarketpoints.com/post/mark-minervini-s-sepa-methodology-complete-framework-explained)

**Rule:** Trend Template Checklist (Stage 2 filter):
  1. Price > 150-day MA > 200-day MA (both moving upward ≥1 month)
  2. 50-day MA > 150-day MA and 200-day MA
  3. Price > 50-day MA
  4. Price ≥30% above 52-week low (ideally within 25% of 52-week high)
  5. RS rating in top 30% (80–90+ preferred)
  6. Earnings growth ≥25% YoY, accelerating sales, strong margins
  7. Risk management: stop-loss ≤ 7–8% below entry (strict discipline)

- **Application to JARVIS:** NOT IMPLEMENTED. Minervini is equity-centric; JARVIS trades futures/options (MES, MCL, MNQ). Stage 2 concept could adapt to futures: apply MA filters + RS equivalent (relative momentum vs sector) + near-term swing high setup. Requires new TechnicalAnalystAgent overlay.
- **Risk of adoption:** 25% earnings growth requirement filters out early cyclical trades. 30% above 52-week low can miss bottoming plays. Recommend: use as final confirmation gate (high-probability entries only), not standalone system. Adapt to futures: skip earnings, use volatility regimes + swing structures instead.

---

## John Carter / TTM Squeeze
**Known for:** Volatility expansion entry specialist. SimpleTrading founder. TTM = Thinkorswim Trade Management.

**Quote:** "The squeeze fires when Bollinger Bands contract enough to fit inside Keltner Channels, signaling extremely low volatility and a potential upcoming breakout. Enter on the first green dot after one or more red dots."
- **Source:** [StockCharts.com — TTM Squeeze](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/ttm-squeeze) | [SimpleTrading — TTM Squeeze Explained](https://www.simplertrading.com/news/ttm-squeeze-explained) | [John Carter PDF](https://www.barchart.com/media/education/pdf/The%20Squeeze%20by%20John%20Carter.pdf)

**Rule:** 
  - Entry: First green dot (momentum expanding) after ≥5 red dots (squeeze phase). Momentum histogram direction = trade direction (above zero = long, below zero = short).
  - Profit-taking: Cash profits at bar 4 of green dot expansion. Trail stop or break even.
  - Context: Works best in volatile breakout regimes; avoid in choppy/range-bound markets.

- **Application to JARVIS:** PARTIALLY IMPLEMENTED. Volatility indicators exist (ATR, Bollinger Bands), but squeeze-specific momentum histogram NOT wired to TraderAgent. Could add: when TechnicalAnalystAgent detects squeeze fire, auto-flag high-probability breakout entry.
- **Risk of adoption:** Whipsaws in false breakouts. Green dots can appear in dead-cat bounces. Recommend: gate with volume confirmation (volume expansion on break), 15-minute minimum consolidation before entry, position size half-normal on squeeze trades (wider stops = more risk).

---

## SUMMARY TABLE: Adoption Status by Trader

| Trader | Rule | Currently Implemented | Recommendation | Priority |
|--------|------|----------------------|-----------------|----------|
| Paul Tudor Jones | 2% max risk per trade, 2:1 RRR | Partial (5% max, no RRR gate) | Tighten risk floor + add RRR validator | P1 |
| Linda Raschke | ADX > 30 + first 20-EMA pullback | No | Add TechnicalAnalystAgent overlay (daily/4H only) | P2 |
| Al Brooks | Clean bar breakouts (body > 70% range) | No | Intraday-only enhancement; defer to Phase 2 | P3 |
| Stan Druckenmiller | Conviction-based position sizing | Partial (equal weighting, 2 micro-contract cap) | Conditional upsizing gate: conviction > 0.75 + confluence > 0.60 | P1 |
| Ernie Chan | Walk-forward validation, Sharpe vs Calmar | Partial (framework exists, not validated live) | Validate OOS degradation; lock backtest window | P0 |
| James Simons | Signal orthogonality, decorrelation | Aspirational (11 agents, not thousands) | Reframe as "inspiration," not "playbook" | P3 (docs only) |
| Mark Minervini | Stage 2 trend template + RS filter | No | Adapt MA logic to futures; add as confirmation gate | P2 |
| John Carter | TTM Squeeze volatility expansion | Partial (indicators exist, not wired) | Add squeeze detection + momentum gating | P2 |

---

## CRITICAL FINDINGS

1. **No direct quote found for Simons.** Medallion methods are proprietary secrets. "Signal orthogonality" is inferred from MIT PhD papers + public interviews, not verified quotes. **Recommend: remove or reframe as architecture inspiration only.**

2. **Chan's rule is most production-ready.** Walk-forward framework already exists. Next: validate OOS Sharpe degradation vs backtest predictions.

3. **Jones + Druckenmiller sizing rules conflict with current JARVIS cap (2 micro-contracts).** Need business decision: remain conservative (current) or conditional escalation (Druckenmiller-style).

4. **Raschke + Brooks + Carter are all intraday/short-timeframe focused.** JARVIS currently scans daily/4H. Scope creep risk if adding 5/1-minute bar logic.

5. **Minervini (equities) doesn't map cleanly to futures.** Earnings growth/RS rating don't apply to MCL/MNQ. Trend template (MA logic) could adapt; stop-loss % is already in system.

---

## NEXT STEPS

1. **Immediate (P0):** Validate Ernie Chan's walk-forward window lock. Is backtest period frozen? Is OOS live tracking active?
2. **Short-term (P1):** Add RRR validator gate at TraderAgent. Tighten risk floor per Paul Tudor Jones (2% hard cap).
3. **Medium-term (P2):** Add Raschke ADX + 20-EMA overlay OR Carter TTM Squeeze detection. Pick one; both require debate orchestrator changes.
4. **Deferred (P3):** Al Brooks bar quality (intraday only, defer Phase 2). Minervini (equity-focused, needs adaptation). Simons (docs only—proprietary).

