# Strategy Synthesis — from Discord digest

Source: `C:\Users\mattm\discord-export\digest-raw\by-module\strategy.json` (31 items, 10-day window ending 2026-04-16).

## TL;DR

- The "strategy" bucket is mostly duplicates-of-what-we-already-shipped and noise. Two genuinely actionable items stand out: the Taleb-persona tail-risk advisor and the Brier-score calibration loop for the debate system. Three items are infrastructure-adjacent (options backtesting, persona ensemble, MTF bias table) worth a short spike but not a sprint.
- **Novel techniques worth evaluating: 5**
- **Status as of 2026-04-17: 5 of 5 SHIPPED** (Novels #1, #2, #3, #4, #5 all integrated as research/discovery tools with Protocol-DI; live wiring deferred per Tier 3 review process)
- **Already implemented (dedup): 7**
- **Noise / misclassified: 19**

## Already in jarvis-trader (dedup)

- **AEGIS GEX / Call Walls / Put Walls / GEX Flip / Vanna / Charm** — `https://x.com/therealdrip2rip/status/2044114750771212618` AND `https://www.tradingview.com/script/Wtxy5arU-MY-FREE-GAMMA-LEVELS/` — same author, same concept. Already parsed by `engine/data/tv_indicator_bridge.py` (fields `tv_gex_flip`, `tv_call_wall`, `tv_put_wall`, `tv_hvl`, `tv_vol_trigger_up/down`) and wired into the gamma-regime hint generator at `engine/agents/technical_analyst.py:193-203` and `:904-940`. Validated by `engine/tests/test_gamma_levels_parser.py`.
- **"Math behind combining 50 weak signals" (@RohOnChain)** — `https://x.com/RohOnChain/status/2041180375838498950` — this IS the paper that ic_ensemble.py cites by name. See `engine/analytics/ic_ensemble.py:29-30` ("Based on @RohOnChain's `Math Behind Combining 50 Weak Signals Into One Winning Trade`"). Wired at `engine/agents/debate.py:265-276, 314-320`.
- **30-min ORB strategy (@boxtradervk)** — `https://x.com/boxtradervk/status/2044168616158081505` — already implemented as a first-class signal stack: `engine/backtest/orb_signals.py` (signal gen), `engine/backtest/orb_backtester.py`, `engine/backtest/orb_walk_forward.py`. Composite weights at `engine/backtest/composite_signals.py:49-51` (TRENDING: STC 0.60, ORB 0.30, VWAP 0.10).
- **MTF Candle Bias Table** — `https://www.tradingview.com/script/sNA3wTTg-MTF-Candle-Bias-Table/` — multi-timeframe alignment already exists in three forms: `engine/analytics/mtf_analyzer.py` (STC alignment across 1h/4h/1d), `engine/backtest/mtf_filter.py`, `engine/analytics/mtf_confirmation.py`.
- **Multi-layer Bayesian reasoning bot (@gustafssonkotte)** — `https://x.com/gustafssonkotte/status/2043940786664886665` — this is structurally the Stage-2 debate stack: `engine/agents/debate.py` (bull/bear evidence, prior belief, advisor refinement), `engine/agents/bull_researcher.py`, `engine/agents/bear_researcher.py`, `engine/agents/advisor_client.py`. Bayesian optimizer exists at `engine/backtest/bayesian_optimizer.py`.
- **Multi-persona agent ensemble (virattt/ai-hedge-fund)** — 19 investor-persona agents (Buffett, Graham, Burry, Taleb, etc.). Structurally identical to the existing bull/bear/advisor debate at `engine/agents/debate.py`. Dedup on architecture; see "Novel" below for the one persona worth extracting.
- **Polymarket tooling (3 repos)** — `runesleo/polymarket-toolkit`, `agent-next/polymarket-paper-trader`, and the @gustafssonkotte / @retrovalix / @n01ennn posts — Polymarket router already exists at `engine/routers/polymarket_router.py`, `engine/markets/polymarket/strategies.py`, `engine/markets/polymarket/scanner.py`. Outside futures scope per PRIMARY FOCUS DIRECTIVE.

## Novel techniques — ranked by expected impact

### 1. Taleb / tail-risk persona in the debate stack (virattt/ai-hedge-fund) — **SHIPPED 2026-04-16 (gated)**

- **Source**: `virattt/ai-hedge-fund` — https://github.com/virattt/ai-hedge-fund
- **Technique**: Add a Nassim-Taleb-style "tail risk / asymmetric-payoff" researcher agent that explicitly scores kurtosis, worst-case slippage, and gap-risk on the proposed trade. Rejects trades where max-adverse-excursion implied by the stop is asymmetric against us (e.g. MCL news gaps through stop).
- **Implementation**: `engine/agents/tail_risk_researcher.py` (TailRiskResearcherAgent + TailRiskReport, ~270 lines, claude-sonnet-4-6). Wired in parallel with bull/bear at `engine/agents/debate.py:343-365` via `asyncio.gather`. Result attached to `DebateResult.tail_risk_report` and serialised by `to_dict()`. Honesty enforcement: any score ≥0.9 forces `veto=True`; any veto forces `size_multiplier=0.0`.
- **Gate**: env-var `TAIL_RISK_RESEARCHER_ENABLED` (default `false`). Defaults dark — ship-and-flip pattern.
- **Tests**: `engine/tests/test_tail_risk_researcher.py` — 19 tests covering JSON parsing, clamping, veto-honesty, defaults, end-to-end via mocked httpx. All passing 2026-04-16.
- **Still pending**: sizing-side wiring into `engine/agents/trader.py:290-293` (size_multiplier consumed as downgrade factor); short-circuit in trader.py for `veto=True`; Monte Carlo replay of the 2024 WTI flash-gap day. These touch safety-critical sizing logic and warrant explicit Tier 3 review per `.claude/rules/commits.md` before landing.
- **Expected impact**: Small improvement to WFE (the overfit leak metric — target MES WFE 0.09 → 0.20+ by forcing the system to refuse asymmetric trades). Sharpe likely neutral-to-slightly-better. Real win is tail-loss reduction in Monte Carlo.
- **Risk**: Adds another LLM call (~$0.01/trade) when enabled. Veto logic could over-filter in calm regimes — must be rate-limited or tied to VIX > threshold. Low overfitting risk — tail risk is invariant.
- **Effort to ship the agent + tests + gated wiring**: ~3 hours actual (vs medium estimate). Trader-side wiring + Monte Carlo replay still 1-2 days.

### 2. Brier-score calibration loop for the debate/advisor stack (runesleo/polymarket-toolkit) — **SHIPPED 2026-04-16 (class only)**

- **Source**: `runesleo/polymarket-toolkit` (`polymarket-brier` skill) — https://github.com/runesleo/polymarket-toolkit
- **Technique**: Every pipeline debate emits a `p_win` (implied by score). After close, log `brier = (p_win - outcome)^2`. Track per-agent Brier over a rolling window — an agent with high PnL but bad Brier is executing well on someone else's edge; an agent with good Brier but low PnL is a signal source being wasted. Use Brier (not just IC) to re-weight analysts.
- **Implementation**: `BrierCalibrationTracker` class at `engine/analytics/ic_ensemble.py:340-479`. For each trade row, decomposes the agent signal into `confidence = |signal|` and `correct = 1 if sign(signal) == sign(pnl) else 0`, then computes per-trade Brier `= (confidence - correct)²`. Mean over rolling window (default 30 days, min 5 trades) is the agent's Brier score. Weights are derived as `w_i ∝ 1 / (brier_i + ε)` normalized to sum 1.0 — well-calibrated agents get more weight, confidently-wrong agents get down-weighted. Uses the **`BRIER_NEUTRAL = 0.25`** sentinel for insufficient-data so "no data" is explicitly distinct from "perfect calibration = 0.0". Zero-magnitude signals are excluded from the mean (the agent had no opinion on that trade).
- **Tests**: `engine/tests/test_brier_calibration.py` — 8 tests covering perfect calibration → low Brier, confident-and-wrong → high Brier, cautious-agent → middling Brier, insufficient-data → 0.25 sentinel, missing-DB → 0.25 (graceful), weight reallocation favours calibrated agent over confidently-wrong, zero-signal trades excluded, describe() snapshot shape. All passing 2026-04-16 in 0.37s.
- **NOT live-wired**: `engine/agents/debate.py` does NOT yet consume `tracker.get_calibration_weights()` (verified by grep — no references to `BrierCalibrationTracker`). Same ship-DARK pattern as the other Novels — wiring touches debate-stack weighting which warrants Tier 3 review per `.claude/rules/commits.md`.
- **Expected impact**: Sharpe +0.2-0.4 by catching well-calibrated-but-quiet agents the IC ensemble currently mutes. Directly addresses the current trap where IC rewards loud agents regardless of calibration.
- **Risk**: Requires trades-with-probabilities data (we already have it via score → sigmoid). Low conflict — pure metric layer. Watch for early-window noise; enforce N≥5 trades before Brier kicks in (current default).
- **Effort**: ~1 hour actual for class + 8 tests (vs <1 day estimate). Live wiring into `debate.py` next to the existing `ICWeightedEnsemble` weight blend is the deferred work.

### 3. Options-strategy backtester with real chains (pyquantnews / Optopsy) — **SHIPPED 2026-04-17 (scaffold)**

- **Source**: `@pyquantnews` (Optopsy) — https://x.com/pyquantnews/status/2043753145306669328
- **Technique**: Use Optopsy-style historical chain replay (free Optopsy data dump they link) to backtest vertical spreads and covered calls against the existing MES/MNQ signal timestamps. Current `engine/options/` modules (`chain_fetcher.py`, `strategy_executor.py`, `position_manager.py`) can price and execute live but have no offline replay.
- **Implementation**: `engine/backtest/options_backtester.py` (~360 lines). Reuses the existing `OptionsChain` and `OptionsContract` dataclasses from `engine/options/chain_fetcher.py` (no duplication). Components: `Signal` / `OptionsLeg` / `VerticalSpread` / `BacktestTrade` / `BacktestResult` dataclasses; `ChainProvider` / `SignalSource` / `SlippageModel` Protocols for dependency injection; `FlatSlippage(bps=5.0)` default model (mid + half-spread + bps); pure helper `select_vertical_spread(chain, direction, target_delta=0.30, width_strikes=1)` for strike picking; `OptionsBacktester.run(underlying_prices_at_expiry)` orchestrator that opens spreads at signal time, holds to expiry, and computes intrinsic-value exits. Tracks two distinct skip reasons (no_chain vs no_strikes) so debugging real backtests is precise. `BacktestResult.to_dict()` serialises `inf` PF as the string `"inf"` for JSON safety.
- **Tests**: `engine/tests/test_options_backtester.py` — 29 tests covering slippage math (BUY adds, SELL subtracts, sell-floored-at-zero), strike selection (bull call → 30-delta long + adjacent OTM short, bear put → mirror), validation rejections (direction, delta range, width), leg P&L (open returns 0, long winner, short winner with negative quantity), spread math (debit, credit, width-debit max profit), result aggregates (empty, all-winners → ∞ PF, mixed P&L), end-to-end runs (winner via underlying rally, loser via OTM expiry, no-chain skip, no-strikes skip, empty signals, missing-expiry-price skip), validation, and intrinsic-value 4-corner test (call/put × ITM/OTM). All passing 2026-04-17 in 0.23s.
- **NOT live-wired**: Pure offline research tool. Does NOT modify `trader.py`, `pipeline.py`, `risk_manager.py`, or `engine/options/strategy_executor.py`. Promoting an option-overlay finding to production is a separate human-reviewed PR per `.claude/rules/commits.md`.
- **DEFERRED to follow-up sessions** (the "large effort" parts of the original estimate): covered calls (require underlying-position tracking), iron condors / butterflies (multi-leg coordination), early-exit rules (50% profit-target, 21-DTE roll), full chain replay against the 2024–2025 MCL/MES signal set, slippage model calibration against historical fills.
- **Expected impact**: Unblocks the option-overlay question (does buying puts against MES longs improve WFE?). Not a PF/Sharpe win directly — an option to translate futures edge into defined-risk options plays for small accounts.
- **Risk**: Large data footprint. Slippage modeling for options is hard. Overfitting risk HIGH if you tune strikes per-trade. Mitigated by the offline-only / human-PR pattern of the scaffold.
- **Effort**: ~2 hours actual for scaffold + 29 tests (vs large >3 days estimate). The deferred items are where the remaining >3 days lives.

### 4. Paper-trader "agent competition" harness (@zostaff) — **SHIPPED 2026-04-16**

- **Source**: `@zostaff` 10-bot competition — https://x.com/zostaff/status/2043719394766073909
- **Technique**: Run N candidate strategies (different STC/ATR/regime parameter sets, or STC vs ORB vs VWAP-alone) as parallel paper-trading "agents" each with $X virtual capital. Winner-takes-all weight allocation over a rolling 30-day window.
- **Implementation**: `engine/strategy_lab/competition_harness.py` (~270 lines). `CompetitionHarness` class tracks N `Competitor` objects; each closed trade is injected via `record_trade()`. `score_window()` evaluates all competitors over a rolling window (default 30 days) using one of four metrics — `pf_sqrt_n` (default; PF × √N rewards both quality and sample size), `sharpe`, `pf`, or `pnl` — and reallocates weights via numerically-stable softmax with configurable temperature (argmax fallback at temperature=0). Survivorship-bias guard: `revive_losers=True` resets each competitor's capital to `starting_capital` after every window so weight is the only persistent state. `min_trades_for_scoring=5` zeros under-traded competitors so a single lucky trade can't dominate.
- **Tests**: `engine/tests/test_competition_harness.py` — 20 tests covering PF math (winners-only=∞, losers-only=0, mixed, empty), Sharpe (zero-variance=0, single-trade=0, consistent-winner>0), softmax (sums-to-1, temperature=0 argmax, empty-input), construction (equal-weight init, validation rejections), trade ingestion (capital update, unknown-strategy KeyError), weight concentration on winner, under-traded skip, revive-losers behavior, window history snapshots, and `to_dict()` shape. All passing 2026-04-16 in 0.31s.
- **NOT live-wired**: Pure research/discovery tool. Live wiring would have `engine/strategy_lab/strategy_loop.py` call `harness.record_trade()` per closed trade and `engine/agents/trader.py` consume `harness.weights[strategy_id]` as a per-strategy size multiplier — both touch sizing logic and warrant Tier 3 review per `.claude/rules/commits.md`. Today the harness is invoked offline against historical paper-trade outcomes.
- **Expected impact**: Walk-forward robustness up — active discovery of regime-specific parameter sets without re-running the Bayesian optimizer. Modest WFE improvement.
- **Risk**: Survivorship bias if you only keep winners — mitigated by `revive_losers=True` default. Softmax temperature must be tuned so weights aren't either too peaked (winner takes 100%) or too flat (no signal). Default `temperature=1.0` matches the AI Hedge Fund Team multi-agent allocation pattern.
- **Effort**: ~2 hours actual (vs medium 1-3 days estimate).

### 5. Statistical arbitrage (MCL-vs-MNQ-vs-MES cointegration screen) (@moondevonyt) — **SHIPPED 2026-04-16**

- **Source**: `@moondevonyt` stat-arb post — https://x.com/moondevonyt/status/2043717588887507257
- **Technique**: Rolling Engle-Granger cointegration between the three futures (MCL-MES, MCL-MNQ, MES-MNQ). When the spread z-score exceeds ±2, open a mean-reverting pair (long the laggard, short the leader) sized to offset directional exposure. Would add a new signal source independent of STC/ORB/VWAP.
- **Implementation**: `engine/analysis/pair_spread.py` (~270 lines). Engle-Granger 2-step implemented manually with scipy + numpy (no statsmodels dep — would add ~70MB). Step 1: OLS hedge-ratio `y = α + β·x + ε` via closed-form `(X'X)^-1 X'y`. Step 2: Mean-reversion test on residuals via AR(1) regression `Δs_t = α + λ·s_{t-1} + ν_t`, then half-life `= -ln(2)/ln(1+λ)` when `λ ∈ (-2, 0)`. Spreads with infinite or > `half_life_max` (default 20 bars) half-life are filtered out. Signal: `LONG_PAIR`/`SHORT_PAIR` when `|z| > z_entry` (default 2.0), `FLAT` when reverted (`|z| <= z_exit`, default 0.5) or non-cointegrated. `screen_all_pairs(price_dict)` produces all C(N,2) pair results with stable alphabetical ordering.
- **Tests**: `engine/tests/test_pair_spread.py` — 23 tests covering hedge-ratio recovery (exact + noisy), spread zero-on-perfect-fit, AR(1) half-life recovery, random-walk noise floor, z-score sign correctness, full pair-screen (cointegrated → tradeable signal, random walk → FLAT at strict threshold), insufficient-obs handling, length-mismatch rejection, pandas Series acceptance, and 3-symbol all-pairs permutation. All passing 2026-04-16 in 0.30s.
- **Known limitation discovered during testing**: Pure Engle-Granger without an ADF significance gate has a measurable false-positive rate on finite-sample independent random walks — a 300-bar pair of independent random walks can occasionally show half-life ≈ 15 bars by chance. Documented in module docstring; production use must pair with a strict `half_life_max <= 5-10` threshold AND regime gating (e.g., only screen during VIX-elevated periods when spreads are likely co-driven).
- **NOT live-wired**: Wiring into `engine/agents/pipeline.py` as a sibling to Hidden Pivots (`:537-585`) requires reasoning about short-leg sizing in `engine/agents/safety_layer.py` and kill-switch logic — Tier 3 review per `.claude/rules/commits.md`.
- **Expected impact**: Sharpe is the right metric — stat-arb is low-PF, high-Sharpe. Expect portfolio Sharpe lift of 0.3-0.5 if spreads are genuinely cointegrated.
- **Risk**: MCL and equity futures are not historically cointegrated except during crises; spread can diverge for months. Requires short legs which the current paper account supports but kill-switch logic does not yet reason about.
- **Effort**: ~2 hours actual for the math + tests (vs medium 1-3 days estimate). Live wiring + kill-switch integration is the deferred large work.

## Noise / passed

- `virattt/ai-hedge-fund` — equities, not futures; architecture already covered (see dedup).
- `algoman123/dashboard123` — Portfolio123 UI, not a signal.
- `rohitg00/agentmemory` — agent memory lib, misclassified.
- `forrestchang/andrej-karpathy-skills` — CLAUDE.md tips, not strategy.
- `AgriciDaniel/claude-obsidian` — note-taking plugin.
- `runesleo/polymarket-toolkit` — useful Brier concept extracted above; rest is Polymarket-only.
- `agent-next/polymarket-paper-trader` — Polymarket, out of scope.
- `freqtrade/freqtrade-strategies` — crypto, uses Hyperopt-overfit strategies (2018 backtest windows). Nothing transferable.
- @lummox_eth "Claude traded 10 copytrading strategies" — generic clickbait, no specific technique.
- @n01ennn "Polymarket edge detector" — Polymarket.
- tradingcomposure.com "Trading Rollercoaster" — trader psychology blog.
- @alphabatcher "AI Agency $0→$10K/mo" — business content, not strategy.
- @pyquantnews second tweet (Optopsy follow-up) — duplicate of #3 above.
- @alphasignalai "Anthropic 512K line code leak" — infra news.
- @gustafssonkotte "Polymarket BTC 15-min bot" — Polymarket.
- @retrovalix "Polymarket trader $230K" — Polymarket.
- @intuitiveml "Your AI-First Strategy Is Probably Wrong" — generic op-ed.
- @0xtengen_ "Stanford Sports Prediction Math lecture" — sports-betting, out of domain.
- @shannholmberg "autoreason for marketing" — marketing use case.
- @jfsrev single-link reply, no content.
- @minara "21 money-printers from 236 TV strategies" — teaser, no technique disclosed.
- @coreyganim "AI predictions for 2026" — industry commentary.

## Raw grep receipts

```
Grep pattern="gamma|GEX|dealer|vanna|charm"    -i → 17 files (tv_indicator_bridge.py, technical_analyst.py, test_gamma_levels_parser.py confirmed)
Grep pattern="ORB|opening_range"               -i → 41 files (orb_signals.py, orb_backtester.py, orb_walk_forward.py, composite_signals.py confirmed)
Grep pattern="multi.?timeframe|MTF"            -i → 32 files (mtf_analyzer.py, mtf_filter.py, mtf_confirmation.py confirmed)
Grep pattern="statistical.?arb|cointegration"  -i → 0 matches (novel — see #5)
Grep pattern="prior.?probab|bayesian"          -i → 3 files (bayesian_optimizer.py, strategy_evaluator.py, wfe_router.py — optimizer-only, not per-trade prior)
Grep pattern="taleb|tail.?risk|antifragil"     -i → docs only, no code (novel — see #1)
Grep pattern="brier|calibration"               -i → docs only, no code (novel — see #2)
Grep pattern="call_wall|put_wall|gex_flip"     → test_gamma_levels_parser.py, technical_analyst.py, tv_indicator_bridge.py (confirmed wired)
Grep pattern="weak.?signal|ensemble|stacking"  -i → ic_ensemble.py (cites RohOnChain by name at line 29-30)

Read engine/analytics/ic_ensemble.py:1-40               → "Based on @RohOnChain's 'Math Behind Combining 50 Weak Signals...'"
Read engine/agents/technical_analyst.py:193-203,904-940 → gamma hints wired into pipeline indicators dict
Read engine/backtest/composite_signals.py:49-51         → STC+ORB+VWAP regime-weighted blend already live
Read engine/backtest/orb_signals.py:1-37                → full RTH opening-range breakout implementation for MES
```

Engine cross-reference confirms the seven dedup items and leaves the five novel items standing.
