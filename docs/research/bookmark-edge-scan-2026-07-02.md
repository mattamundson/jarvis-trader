---
title: X-Bookmark Trading-Edge Scan — 2026-07-02
date: 2026-07-02
tags: [trading, x-bookmarks, edge-scan]
---

# X-Bookmark Trading-Edge Scan — 2026-07-02

## Executive Summary

Scanned the 200 newest trading-relevant X bookmarks (weeks 2026-W27 + W26), links pre-enriched, run through a 20-way fan-out analysis and an adversarial verify/dedupe/tier pass with an economic-rationale gate.

**Yield funnel:**

| Stage | Count |
|---|---|
| Bookmarks analyzed | 200 |
| Trading-relevant | 58 |
| Raw hypotheses | 30 |
| Backtestable | 29 |
| **Survivors (post-dedupe)** | **19** |
| **Tier-A (backtest now)** | **2** |

Ten duplicate hypotheses were merged. The batch is dominated by two themes:

1. **Dealer-gamma / GEX regime trading** — 6 near-identical hypotheses collapsed into one canonical edge: *mean-revert when dealers are long gamma, trade momentum when they are short gamma.*
2. **Trend / momentum on equity indices** — `sma12` monthly, `supertrend` weekly, ATR-band, Kaufman-ER adaptive trend (same risk-premium family, different horizons/exits).

Only **two Tier-A candidates** are ready for a full backtest now with no exotic data: **`sma12_monthly_momentum`** (highest conviction, well-replicated time-series momentum) and **`spy_overnight_hold`** (trivially testable close-to-open anomaly). Most Tier-B edges are real but gated on an instrument/data decision (GEX feed, SPX options + delta-hedge sim, or an equities pipeline) — none native to the ES futures engine. The Tier-C tail (ICT/SMC zones, 9EMA reclaim, Wyckoff, IB/ORB family) has thin, discretionary rationales and high multiple-testing risk; run only under a shared global trial counter with PBO / permutation gating.

---

## Ranked Survivors

### Tier A — backtest now (no exotic data)

#### 1. `sma12_monthly_momentum`
- **Symbol:** SPX / ES
- **Direction:** long
- **Timeframe:** monthly bars
- **Thesis:** Long the index when the monthly close is above its 12-month SMA; flat to cash below. SMA beats EMA for this filter.
- **Economic rationale:** Time-series (absolute) momentum risk premium — persistent trend autocorrelation documented across assets (Moskowitz–Ooi–Pedersen). The filter truncates left-tail drawdowns by exiting sustained downtrends. Strongest, most-replicated edge in the batch.
- **Param sketch:** Entry monthly close > 12mo SMA; exit close < SMA; execute at close or next open; ~70% time in market. Test on a continuous ES/MES back-adjusted series. Test SMA vs EMA and month-close vs next-open fill; benchmark risk-adjusted (Sharpe / MaxDD) vs buy-and-hold.
- **Confidence:** high
- **Dedupe note:** Distinct from `supertrend_weekly` (monthly TS-momentum vs weekly volatility-trailing-stop).
- **Sources:** [QuantifiedStrat](https://x.com/QuantifiedStrat/status/2072002224553603121)

#### 2. `spy_overnight_hold`
- **Symbol:** SPY / ES
- **Direction:** long
- **Timeframe:** daily close-to-open
- **Thesis:** Buy MOC, sell MOO next session; flat intraday. Capture the overnight drift.
- **Economic rationale:** Well-documented close-to-open drift / overnight risk-premium anomaly — the bulk of SPY's historical return accrues overnight while intraday is ~flat (overnight risk-bearing compensation + index-futures fair-value carry). Trivially testable, no options/microstructure data needed.
- **Param sketch:** Entry buy MOC, exit sell MOO; optional VIX-regime / prior-day-return filter; benchmark vs buy&hold; test SPY cash vs overnight ES session for futures translation.
- **Confidence:** med
- **Sources:** [QuantifiedStrat](https://x.com/QuantifiedStrat/status/2070190285746036963)

### Tier B — real edges, gated on instrument/data decision

#### `dealer_gamma_regime`
- **Symbol:** SPX / SPY / ES · **Direction:** both · **Timeframe:** intraday (regime set at premarket)
- **Thesis:** The sign of net dealer gamma sets the day's regime: negative GEX / spot below gamma-flip → vol expansion, trade momentum/breakout; positive GEX / spot above flip → vol suppression + pinning, fade extremes toward gamma-neutral/wall. Exit EOD.
- **Economic rationale:** Options-dealer delta-hedging microstructure. Short-gamma dealers hedge pro-cyclically (buy strength / sell weakness), amplifying moves; long-gamma dealers hedge counter-cyclically, dampening vol and pinning to large-gamma strikes. Mechanical, non-news flow.
- **Param sketch:** Compute daily net GEX + zero-gamma flip from options OI (SpotGamma / MenthorQ / Unusual Whales or own chain); GEX<0 or spot<flip → opening-range breakout; else fade to prior VWAP / nearest wall; exit EOD. **Needs a GEX data-feed decision before it can run on the ES engine.**
- **Confidence:** med
- **Dedupe note:** MERGED 6 near-identical GEX/gamma hypotheses (`gex_dealer_gamma_regime`, `gex_negative_gamma_momentum`, `gex_flip_spy`, `dealer_gamma_regime`, `spx_gamma_pin`, `qqq_gamma_flip_regime`) into one canonical edge.
- **Sources:** [Limitlesss1 a](https://x.com/Limitlesss1/status/2069197464343888202) · [Limitlesss1 b](https://x.com/Limitlesss1/status/2069555418595238371) · [Limitlesss1 c](https://x.com/Limitlesss1/status/2069526577050968450) · [MenthorQpro a](https://x.com/MenthorQpro/status/2071983816386764982) · [MenthorQpro b](https://x.com/MenthorQpro/status/2071934987486568662) · [TailThatWagsDog](https://x.com/TailThatWagsDog/status/2072129706590400851)

#### `supertrend_weekly_spx`
- **Symbol:** SPX / ES · **Direction:** long · **Timeframe:** weekly
- **Thesis:** Long S&P on weekly Supertrend (ATR10, mult3) buy signal; flat to cash on sell. Long-only.
- **Economic rationale:** Multi-week trend-following momentum persistence in equity indices; a volatility-scaled trailing stop cuts time-at-risk and drawdown vs buy-and-hold. Same premium family as `sma12` but different horizon/exit mechanic. (Claim: 60yr DD 24.6% vs 56% B&H, 37% time out of market.)
- **Param sketch:** Supertrend ATR=10, mult=3, weekly bars, long-only, flat below band. Compare to `sma12` and buy&hold; watch for over-tuned multiplier (grid 2–4).
- **Confidence:** med
- **Dedupe note:** Kept separate from `sma12`; overlaps in spirit — backtest jointly to avoid double-counting the trend premium.
- **Sources:** [QuantifiedStrat](https://x.com/QuantifiedStrat/status/2071956929237123252)

#### `atr_band_breakout`
- **Symbol:** ES · **Direction:** both · **Timeframe:** intraday/daily
- **Thesis:** Bands at MA ± k·ATR; long on close above upper, short below lower; exit on return to MA. Test breakout vs mean-reversion polarity.
- **Economic rationale:** Volatility expansion after contraction tends to trend; ATR-scaling adapts entry distance to current vol so signals fire on regime shifts not noise. Directly on ES, no exotic data.
- **Param sketch:** MA=20, ATR=14, k=2–3; entry close beyond band; exit cross to MA or opposite band. **Must test both polarities** — direction of edge is the open question.
- **Confidence:** med
- **Sources:** [QuantifiedStrat](https://x.com/QuantifiedStrat/status/2072047523917885657)

#### `kaufman_efficiency_adaptive_trend`
- **Symbol:** ES · **Direction:** both · **Timeframe:** intraday/swing
- **Thesis:** Kaufman Efficiency Ratio drives an adaptive MA + ATR bands: trade with trend when ER high (bands tighten), stand aside in low-ER chop.
- **Economic rationale:** ER measures signal-to-noise of price travel; trend edge concentrates in high-efficiency regimes and bleeds in chop — regime-conditioning is a real filter. Portable Pine logic already exists.
- **Param sketch:** ER len=10; adaptive MA 2/30; long when price>AMA & ER>0.5 & signal-score>60; ATR-band exit. Port the free non-repainting Pine indicator's logic to the ES engine.
- **Confidence:** med
- **Sources:** [WillyAlgoTrade](https://x.com/WillyAlgoTrade/status/2071679831733838313)

#### `rth_open_liquidity_sweep_reversion`
- **Symbol:** ES · **Direction:** both · **Timeframe:** intraday 1–5m, RTH open
- **Thesis:** Map prior-day / overnight high & low; when price sweeps a level in first 60–90m of RTH and fails to hold, fade back toward the opposite pool / session VWAP.
- **Economic rationale:** Stop-loss and breakout orders cluster at obvious prior highs/lows; price is drawn to trigger them (liquidity grab), then reverts once fuel is exhausted. Classic stop-hunt microstructure/behavioral edge.
- **Param sketch:** Levels = prior RTH high/low + overnight high/low; entry = sweep + rejection candle within first 90m; stop beyond sweep extreme; target opposite liquidity or VWAP. Cleanly testable on ES intraday bars.
- **Confidence:** med
- **Sources:** [Equ1ty_Engineer](https://x.com/Equ1ty_Engineer/status/2070991073393131904)

#### `delta_hedged_short_straddle_vrp`
- **Symbol:** SPX · **Direction:** short · **Timeframe:** weekly entry / daily hedge / 7-DTE
- **Thesis:** Sell 7-DTE ATM straddle each Friday, delta-hedge every 24h, hold to expiry at constant notional; harvest IV-minus-RV.
- **Economic rationale:** Variance risk premium — implied persistently exceeds realized because investors overpay for crash/vol insurance; delta-hedging strips direction to isolate the premium. Among the strongest rationales in the batch, but a short-vol/tail-risk collector (needs strict sizing + tail hedge). (Author claim: 1.99 Sharpe.)
- **Param sketch:** Fri 08:00 sell ATM 7DTE straddle; re-hedge to flat every 24h; $100k constant notional; exit at expiry. **Requires SPX options chain + delta-hedge sim — NOT native to the ES engine; instrument/infra decision needed. Gate hard on MC tail-drawdown** given short-gamma profile.
- **Confidence:** med
- **Sources:** [ThalexGlobal](https://x.com/ThalexGlobal/status/2072199609560990016)

#### `vol_target_deleveraging_downside`
- **Symbol:** ES · **Direction:** short · **Timeframe:** daily, 1–3 day horizon
- **Thesis:** After a sharp down day with a realized-vol spike, expect continued/accelerating downside over 1–3 days as vol-targeting funds mechanically deleverage.
- **Economic rationale:** Risk-parity / vol-targeting funds cut equity exposure when realized vol jumps; forced, price-insensitive, clustered selling creates positive-feedback downside ('elevator down') asymmetric to the slower grind up.
- **Param sketch:** Trigger 1d return < −1.5% AND realized-vol jump > Xth pctile; short ES; exit after 3 days or vol mean-reversion. **Explicitly test up/down asymmetry** so it isn't just short-bias in a bull sample.
- **Confidence:** low
- **Sources:** [ConcretumR](https://x.com/ConcretumR/status/2070175840004964514)

#### `stat_arb_pairs`
- **Symbol:** equities (cointegrated pair) · **Direction:** both · **Timeframe:** daily
- **Thesis:** Trade a cointegrated pair's spread z-score: short rich / long cheap leg at |z| threshold, exit on reversion.
- **Economic rationale:** Two economically-linked assets share a common stochastic trend; transient divergence is corrected by relative-value flows — market-neutral mean-reversion. Classic, well-posed, but equities not ES.
- **Param sketch:** Engle-Granger/Johansen cointegration; entry |z|>2, exit |z|<0.5, stop |z|>3.5, rolling 60d hedge ratio. **Needs an equities data pipeline; out-of-scope for a pure futures engine** unless a futures-spread analogue is chosen (calendar/inter-market).
- **Confidence:** med
- **Dedupe note:** Kept separate from `pca_residual_stat_arb` (single explicit pair vs PCA-factor residual on a basket).
- **Sources:** [QuantifiedStrat](https://x.com/QuantifiedStrat/status/2069480354386251856)

### Tier C — thin/discretionary; only under global trial counter + PBO/permutation gating

#### `pca_residual_stat_arb`
- **Symbol:** equity basket · **Direction:** both · **Timeframe:** daily to multi-day · **Confidence:** low
- **Thesis:** PCA-decompose a universe into ~5 factors, trade the mean-reverting idiosyncratic residual per name (s-score).
- **Economic rationale:** Avellaneda–Lee statistical arbitrage — residual after removing systematic factor exposure is Ornstein-Uhlenbeck mean-reverting. Real and cited, but heaviest infra of the batch and not futures.
- **Param sketch:** Rolling 60d PCA; regress each name on top 5 PCs; s-score = residual/rolling-std; enter |s|>1.25, exit |s|<0.5, dollar-neutral. Low priority for a futures desk; capacity/infra dependent.
- **Sources:** [L1vsun](https://x.com/L1vsun/status/2070892216109736002)

#### `ib_orb_session_structure`
- **Symbol:** NQ/MNQ (ES/generic) · **Direction:** both · **Timeframe:** intraday, RTH open · **Confidence:** low
- **Thesis:** Family of opening-auction structure rules: (a) the IB extreme that forms FIRST tends to break first — trade continuation of that side; (b) ORB close sign predicts IB finish direction (bias filter); (c) condition the break on IB width — narrow IB → breakout, wide IB → fade to IB mid.
- **Economic rationale:** Opening-auction order flow: early directional imbalance persists as latecomers chase (continuation), while wide early ranges signal exhausted flow (reversion). Plausible microstructure but low individual confidence and heavy multiple-testing risk across sub-rules.
- **Param sketch:** IB=09:30–10:30 ET; features = first-formed extreme, ORB(5–15m) close sign, IB-width percentile vs trailing 20d; entry stop-breakout or fade per rule; exit EOD or 1R. **Treat as ONE study with a global trial counter, not three edges.**
- **Dedupe note:** MERGED 3 hypotheses (`ib_orb_first_form_break_continuation`, `orb_close_predicts_ib_direction`, `ib_range_width_conditioned_break`).
- **Sources:** [IB/ORB Statistical Mapper](https://www.tradingview.com/script/WPtTm8fg-IB-ORB-Statistical-Mapper-hardcoded/) · [IB/ORB Live Stats](https://www.tradingview.com/script/4NCjPLzS-IB-ORB-Live-Stats/)

#### `rv_iv_meanrev`
- **Symbol:** equities/generic · **Direction:** long · **Timeframe:** daily swing · **Confidence:** low
- **Thesis:** When a name's realized move is large relative to its implied move, buy the mean reversion with a limit.
- **Economic rationale:** Short-horizon overreaction + VRP: a realized move outpacing priced IV signals liquidity-driven overshoot that market-makers lean against. Reasonable but needs per-name IV data and is long-biased (bull-sample risk). (Claim: 27% CAGR, 2.4 Sharpe, 6.3% exposure.)
- **Param sketch:** Trigger |ret_1–5d| > k·IV_daily; limit-buy the extension; exit on revert. Needs options IV feed; not futures-native.
- **Dedupe note:** Kept separate from `delta_hedged_short_straddle_vrp` (directional reversion signal vs delta-hedged premium harvest).
- **Sources:** [SystematicPeter](https://x.com/SystematicPeter/status/2071963726438388033)

#### `ict_smc_zone_reversion`
- **Symbol:** ES · **Direction:** both · **Timeframe:** 5m–1h intraday · **Confidence:** low
- **Thesis:** Fade into ICT/SMC zones: (a) return to an unfilled Fair Value Gap → fade toward gap midpoint; (b) retest of the last opposing 'order block' before an impulse → enter with the block.
- **Economic rationale:** FVGs/order-blocks proxy thin-liquidity / absorbed-institutional-size zones where inventory rebalancing pulls price back. Weakest rationale tier — detection is fuzzy/discretionary and heavily curve-fit-prone; only proceed with strict OOS + permutation tests.
- **Param sketch:** Use `smart-money-concepts` lib for FVG/OB detection; entry on retest, stop beyond zone origin, target midpoint/prior swing; trend filter. **Objectify the detection rules before any claim of edge.**
- **Dedupe note:** MERGED `fvg_fill_reversion` + `order_block_bounce` (same source, same library, same mechanism).
- **Sources:** [tom_doerr](https://x.com/tom_doerr/status/2071305325139939669)

#### `ema_9_20_pullback_15m`
- **Symbol:** ES · **Direction:** both · **Timeframe:** 15m intraday · **Confidence:** low
- **Thesis:** On 15m, long when 9EMA>20EMA and price pulls back into the band then resumes; mirror short; exit next swing pivot.
- **Economic rationale:** Short-horizon trend/momentum persistence via order-flow autocorrelation; pullback entry improves R:R. Generic and over-common; likely thin edge after costs.
- **Param sketch:** Fast 9EMA / slow 20EMA; entry retrace into band in trend direction; stop beyond band; TP prior swing; ATR chop filter. Cheap to test on ES 15m.
- **Sources:** [MapleStax](https://x.com/MapleStax/status/2070265108744557020)

#### `9ema_reclaim_continuation`
- **Symbol:** ES/generic · **Direction:** long · **Timeframe:** intraday 1–5m · **Confidence:** low
- **Thesis:** After price reclaims the 9EMA following a down-move and the pullback holds it as support, go long for the continuation leg.
- **Economic rationale:** 9EMA is a widely-watched reference; clustered stops + momentum-chaser orders above it create a self-fulfilling near-term continuation. Behavioral/order-flow but very thin and crowded.
- **Param sketch:** Entry: close reclaims 9EMA + successful retest; stop below retest low; exit 1.5–3R or first close below 9EMA. Objectify 'retest holds' before testing.
- **Dedupe note:** MERGED `9ema_flip_rally` + `9ema_flip_rally_v2` (identical setup, same author).
- **Sources:** [ThiccTeddy a](https://x.com/ThiccTeddy/status/2069889802229702845) · [ThiccTeddy b](https://x.com/ThiccTeddy/status/2069873447610528005)

#### `pca_regime_factor_overlays`
- **Symbol:** SPX · **Direction:** both · **Timeframe:** daily · **Confidence:** low
- **Thesis:** Use rolling PCA on constituents as a risk overlay: (a) high PC1 variance share → cut single-name/dispersion bets, lean directional; (b) PC3 (rate-sensitivity) variance share spike → hedge equity book's implied rate exposure with duration instruments.
- **Economic rationale:** High PC1 (correlation) share collapses idiosyncratic edge → systematic risk-on/off regime; rising PC3 loading means equity moves are rate-driven → hedge unintended factor exposure. Genuine factor-timing logic but overlay/sizing, not a standalone signal — hard to validate PnL attribution.
- **Param sketch:** Rolling 60d PCA on S&P constituents; PC1 var-share pctile gates directional vs rotation book; PC3 z>2 overlays ZN/ZB hedge sized to PC3 loading. Speculative; requires full equity + rate data stack.
- **Dedupe note:** MERGED `pca_regime_position_sizing` + `pc3_rate_beta_hedge`.
- **Sources:** [thedelost](https://x.com/thedelost/status/2071696872117596210)

#### `wyckoff_accumulation_breakout`
- **Symbol:** generic · **Direction:** long · **Timeframe:** daily/swing · **Confidence:** low
- **Thesis:** After a multi-week range with declining vol and a spring/shakeout low, long the breakout above range highs; target 1× range height.
- **Economic rationale:** Wyckoff accumulation = institutions absorbing supply; the spring flushes weak longs before markup. Behavioral/microstructure narrative but the pattern is discretionary and hard to specify.
- **Param sketch:** Range detect via ATR contraction over 15–30 bars; spring = false break below range low then reclaim; entry close above range high; stop below spring low; target 1× range height. **Must fully objectify range/spring detection to be testable.**
- **Sources:** [ThiccTeddy](https://x.com/ThiccTeddy/status/2072048526834422087)

#### `rl_execution_cost_minimization`
- **Symbol:** generic · **Direction:** both · **Timeframe:** intraday/sub-minute execution · **Confidence:** low
- **Thesis:** RL/DQN execution agent schedules child orders to keep realized slippage below the alpha being captured.
- **Economic rationale:** Execution edge, not alpha — optimal slicing against transient order-book impact preserves signal PnL (Almgren-Chriss / RL execution literature). Legitimate but improves other strategies rather than generating standalone returns.
- **Param sketch:** State = LOB imbalance+spread+remaining qty+time; action = child size/aggression; reward = −(slippage vs arrival); benchmark vs TWAP/VWAP. Needs L2 order-book sim (HftBacktest). **Deprioritize until a live strategy is cost-bound.**
- **Sources:** [RitOnchain](https://x.com/RitOnchain/status/2069323424078688262)

---

## Tooling Finds

| Tool | Link | Why it matters for jarvis-trader |
|---|---|---|
| microsoft/qlib | https://github.com/microsoft/qlib | AI quant platform (45k★): data handlers, alpha-factor library, supervised/RL modeling, backtest, RD-Agent. Most directly reusable infra for factor research + ML signal modeling. |
| backtrader | https://github.com/mementum/backtrader | Mature Python backtest+live library; reference patterns for the engine and for quickly prototyping trend/breakout survivors (`sma12`, `supertrend`, `atr_band`). |
| HftBacktest | https://github.com/nkaz001/hftbacktest | Rust/Python HFT backtester with L2/L3 order-book, queue-position and latency modeling — needed for `rl_execution` and microstructure/liquidity-sweep tests beyond bar-level. |
| MarS (Microsoft Large Market Model) | https://x.com/RitOnchain/status/2071869971337265364 | Open-sourced generative order-flow / market-sim model (16B order tokens) — candidate for LOB simulation and microstructure feature research. |
| Adaptive Volatility Trend [WillyAlgoTrader] | https://x.com/WillyAlgoTrade/status/2071679831733838313 | Free non-repainting Pine indicator (Kaufman-ER adaptive MA + efficiency-scaled ATR bands + 0–100 score). Logic ports directly to `kaufman_efficiency_adaptive_trend`. |
| smart-money-concepts | https://github.com/joshyattridge/smart-money-concepts | Python package computing ICT FVG / order-block / liquidity indicators — objectifies detection for `ict_smc_zone_reversion` and `rth_open_liquidity_sweep`. |
| IB/ORB Statistical Mapper + Live Stats | https://www.tradingview.com/script/WPtTm8fg-IB-ORB-Statistical-Mapper-hardcoded/ | Open-source Pine encoding IB/ORB break-first, continuation, and width-conditioned probabilities per symbol — reference logic for `ib_orb_session_structure` (also /script/4NCjPLzS). |
| Diebold-Mariano test | https://x.com/RuujSs/status/2070139674576953404 | Statistical test of predictive-accuracy differences between two models — complements deflated Sharpe / PBO in the gate stack to confirm a signal beats a simpler baseline. |
| financial-datasets/mcp-server | https://github.com/financial-datasets/mcp-server | MCP server exposing fundamentals + price/crypto data — pluggable equities data source if the stat-arb / PCA survivors are pursued. |
| shashankvemuri/Finance | https://github.com/shashankvemuri/Finance | 150+ Python scripts for indicators, data pipelines, strategy prototypes (4k★) — reusable reference code. |
| NVIDIA cudf.pandas (RAPIDS) | https://github.com/rapidsai/cudf | Drop-in GPU pandas accelerator (~150× on large frames) — speeds backtest/feature-engineering + PCA/Monte-Carlo sweeps. |
| highfestiva/finplot | https://github.com/highfestiva/finplot | Performant Python finance plotting for large candle/indicator sets — backtest and Monte-Carlo dashboard viz. |

---

## Coverage Appendix — trading-relevant bookmarks

| Handle / source | Category | Link | Hypotheses |
|---|---|---|---|
| QuantifiedStrat | strategy | https://x.com/QuantifiedStrat/status/2072002224553603121 | sma12_monthly_momentum |
| QuantifiedStrat | strategy | https://x.com/QuantifiedStrat/status/2070190285746036963 | spy_overnight_hold |
| QuantifiedStrat | strategy | https://x.com/QuantifiedStrat/status/2071956929237123252 | supertrend_weekly_spx |
| QuantifiedStrat | strategy | https://x.com/QuantifiedStrat/status/2072047523917885657 | atr_band_breakout |
| QuantifiedStrat | strategy | https://x.com/QuantifiedStrat/status/2069480354386251856 | stat_arb_pairs |
| Limitlesss1 | indicator/market_view | https://x.com/Limitlesss1/status/2069197464343888202 | dealer_gamma_regime |
| Limitlesss1 | indicator | https://x.com/Limitlesss1/status/2069555418595238371 | gex_negative_gamma_momentum → dealer_gamma_regime |
| Limitlesss1 | strategy | https://x.com/Limitlesss1/status/2069526577050968450 | gex_flip_spy → dealer_gamma_regime |
| MenthorQpro | market_view | https://x.com/MenthorQpro/status/2071983816386764982 | spx_gamma_pin → dealer_gamma_regime |
| MenthorQpro | market_view | https://x.com/MenthorQpro/status/2071934987486568662 | qqq_gamma_flip_regime → dealer_gamma_regime |
| TailThatWagsDog | strategy | https://x.com/TailThatWagsDog/status/2072129706590400851 | gex_dealer_gamma_regime → dealer_gamma_regime |
| WillyAlgoTrade | indicator | https://x.com/WillyAlgoTrade/status/2071679831733838313 | kaufman_efficiency_adaptive_trend |
| Equ1ty_Engineer | strategy | https://x.com/Equ1ty_Engineer/status/2070991073393131904 | rth_open_liquidity_sweep_reversion |
| ThalexGlobal | strategy | https://x.com/ThalexGlobal/status/2072199609560990016 | delta_hedged_short_straddle_vrp |
| ConcretumR | education | https://x.com/ConcretumR/status/2070175840004964514 | vol_target_deleveraging_downside |
| L1vsun | strategy | https://x.com/L1vsun/status/2070892216109736002 | pca_residual_stat_arb |
| SystematicPeter | strategy | https://x.com/SystematicPeter/status/2071963726438388033 | rv_iv_meanrev |
| tom_doerr | indicator | https://x.com/tom_doerr/status/2071305325139939669 | fvg_fill_reversion, order_block_bounce → ict_smc_zone_reversion |
| MapleStax | strategy | https://x.com/MapleStax/status/2070265108744557020 | ema_9_20_pullback_15m |
| ThiccTeddy | strategy | https://x.com/ThiccTeddy/status/2069889802229702845 | 9ema_flip_rally → 9ema_reclaim_continuation |
| ThiccTeddy | strategy | https://x.com/ThiccTeddy/status/2069873447610528005 | 9ema_flip_rally_v2 → 9ema_reclaim_continuation |
| ThiccTeddy | strategy | https://x.com/ThiccTeddy/status/2072048526834422087 | wyckoff_accumulation_breakout |
| thedelost | strategy | https://x.com/thedelost/status/2071696872117596210 | pca_regime_position_sizing, pc3_rate_beta_hedge → pca_regime_factor_overlays |
| RitOnchain | education | https://x.com/RitOnchain/status/2069323424078688262 | rl_execution_cost_minimization |
| RitOnchain | tool | https://x.com/RitOnchain/status/2071869971337265364 | mars_order_flow_synth (tool) |
| RuujSs | education | https://x.com/RuujSs/status/2070139674576953404 | Diebold-Mariano (validation tool) |
| TradingView (IB/ORB Mapper) | indicator | https://www.tradingview.com/script/WPtTm8fg-IB-ORB-Statistical-Mapper-hardcoded/ | ib_orb_session_structure |
| TradingView (IB/ORB Live Stats) | indicator | https://www.tradingview.com/script/4NCjPLzS-IB-ORB-Live-Stats/ | ib_orb_session_structure |

*Non-hypothesis bookmarks (tools, macro market-views, education/mindset threads, methodology critiques, and unspecified promo claims) were reviewed but produced no backtestable rule. Notable: a BIS RNN+LLM market-stress early-warning concept, Howard Marks AI-bubble caution (×2, macro), an overfitting warning ("2 real rules, 10 that prettify the backtest") that reinforces gate-v2 discipline, and a random-portfolio-optimizer critique (use real convex/grid optimizers, not random sampling).*

---

## Method Note

- **Corpus:** 200 bookmarks — the newest trading-relevant set from weeks 2026-W27 + W26.
- **Enrichment:** links pre-enriched (tweet/thread/article text captured where available).
- **Analysis:** 20-way fan-out over the corpus, then an adversarial verify/dedupe/tier pass.
- **Economic-rationale gate:** every survivor must carry a real, statable market mechanism (risk premium, microstructure/order-flow, or behavioral) — pattern-only ideas were killed or demoted to Tier C.
- **Dedupe:** 30 raw hypotheses → 29 backtestable → 19 survivors after merging 10 duplicates (6 GEX/gamma → 1; 3 IB/ORB → 1; 2 FVG/OB → 1; 2 9EMA → 1; 2 PCA-overlay → 1).
- **Downstream:** Tier-A (`sma12_monthly_momentum`, `spy_overnight_hold`) → robust funnel + gate-v2 (Deflated Sharpe, PBO, purged/CPCV, permutation, global trial counter). Tier-B is real but gated on an instrument/data-feed decision (GEX feed, SPX options + delta-hedge sim, equities pipeline). Tier-C runs only under a shared global trial counter with PBO/permutation gating.
