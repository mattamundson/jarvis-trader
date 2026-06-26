---
repo: OnePunchMonk/AgentQuant
url: https://github.com/OnePunchMonk/AgentQuant
stars: 149
language: Python
license: missing (no LICENSE file — treat as proprietary; ideas only, copy no code)
archived: false
pushed_at: 2026 (active; 63 passing tests, CI on py3.10/3.11/3.12)
analyzed_at: 2026-06-22
recommendation: partial-integrate
surfaces_with_value: [engine, docs]
also_covers: quantscience_/investing-algorithm-framework Bitcoin bot tutorial (golden/death cross SMA)
---

# OnePunchMonk/AgentQuant + investing-algorithm-framework tutorial

## Core value proposition

Two sources analyzed together because the user grouped them:

1. **Quant Science / investing-algorithm-framework Bitcoin bot** — an intro tutorial:
   a golden-cross/death-cross SMA(9,50) strategy on BTC/EUR, a CCXT market-data-source
   abstraction, and a text backtest report. Pedagogically clean, but every concept in it
   is **already shipped and exceeded** in jarvis-trader (see dedup map below).

2. **AgentQuant** — an AI research platform that runs a ReAct closed loop
   (Analyze regime -> Hypothesize params via LLM->grid->random fallback -> Backtest
   tournament -> Reflect/retry <=3x -> Store best to SQLite) to autonomously generate and
   validate strategies. yfinance + FRED data, percentile-based VIX regime detection,
   bootstrapped Sharpe p5 confidence intervals, a `WarmupEnforcer` for look-ahead safety,
   and an alpha-candidate memory store.

The honest finding: **~90% of both sources is already implemented here, usually more
rigorously.** The transferable value is a small set of *specific* AgentQuant techniques
plus the cross-asset framing the user actually wants — applying our existing futures
machinery to SPY / SPX / VIX.

## What is already covered (dedup — do NOT re-ship)

| Source concept | Already in jarvis-trader | Verdict |
|---|---|---|
| Golden/death cross SMA strategy | `engine/backtest/trend_signals.py` — SMA(fast,slow) golden-cross entry, death-cross/ATR-trail exit, walk-forward champion params per symbol, RV regime filter | dedup-engine |
| CCXT / market-data-source abstraction | `engine/data/market_data.py`, `polygon_stream.py`, `tradingview_feed.py`, `parquet_cache.py`, `price_cache.py` (TTL caching included) | dedup-engine |
| Text backtest report | `backtest-report` skill + `engine/backtest/backtester.py` metrics | dedup-skill |
| Strategy base class / ABC | `engine/strategies/base_strategy.py`, `registry.py` | dedup-engine |
| ReAct gen->backtest->reflect->store loop | `engine/strategies/discovery_loop.py` + `engine/autoresearch/` + `engine/backtest/candidate_registry.py` (frozen-candidate forward test) | dedup-engine |
| LLM->grid->random fallback chain | `engine/backtest/bayesian_optimizer.py`, `optimizer.py`, `strategies/llm_sandbox.py` | dedup-engine |
| Bootstrapped Sharpe p5 CI | `engine/backtest/deflated_sharpe.py`, `monte_carlo.py`, `cpcv.py` | dedup-engine |
| WarmupEnforcer (look-ahead prevention) | `.claude/rules/testing.md` point-in-time section + `engine/backtest/news_blackout.py`, `regime.py` gating | dedup-rules |
| Calmar / Sortino / max DD metrics | `engine/backtest/metrics.py` | dedup-engine |
| CRISIS regime via VIX | `engine/backtest/regime_classifier.py` (VIX>35 hard threshold) | partial — see below |

## Surface analysis

### 1. Engine code
**partial-integrate** — three genuine gaps:

- **Percentile VIX regime lens.** Our `regime_classifier.py` uses a *fixed* VIX>35
  CRISIS threshold. AgentQuant classifies by rolling VIX percentile
  (Crisis >85th, HighVol >65th, MidVol >35th, LowVol <35th) + a 3-month momentum overlay
  (Bull/Neutral/Bear). Percentile is adaptive to volatility regime drift in a way a fixed
  35 print is not. Add as an *additive* alternate classifier, never replacing the existing
  one (which feeds gate v2).
- **SPX / VIX instrument coverage.** `contract_specs.py` already has SPY/QQQ/IWM but
  **no SPX, no VIX, no VX futures**. This is the actual cross-asset extension the user
  asked for.
- **VIX-as-signal overlay for futures.** `engine/analytics/vix_overlay.py` exists; the
  percentile regime can feed it to gate/scale MES/MNQ trend entries (we already have
  `run_mes_trend_vix_rank*.py` evidence that VIX conditioning helps MES trend).

### 2. Project rules
**dedup-rules** — look-ahead discipline already canonized in `.claude/rules/testing.md`
(cites DeepFund arXiv 2505.11065). AgentQuant's `WarmupEnforcer` (252-bar min) is the
same idea, weaker. No new rule needed.

### 3. Project skills
**no-fit** — `backtest-report`, `jarvis-wfe-check`, `repo-integrator` already cover the
workflow surface.

### 4. Slash commands
**no-fit.**

### 5. Subagents
**no-fit** — `backtest-runner` already covers tournament-style validation.

### 6. Docs
**integrate-now** — this proposal doc + a short strategy note documenting the
percentile-VIX regime mapping for SPY/SPX/VIX once built.

### 7. Dev tooling
**no-fit.**

### 8. Dashboard
**defer** — a regime card (VIX percentile tier + momentum) widget would be a nice
monitoring add, but only after the classifier exists. Use existing badge variants
(`bull|bear|warn|info|neutral`).

### 9. Ops / messaging
**no-fit.**

## Integration plan

> **Status (2026-06-22):** User chose "both options + futures" for the SPX/VIX vehicle and
> authorized proceeding. **Phase 1 SHIPPED**, **Phase 2 SHIPPED**, **Phase 3 primitive
> SHIPPED** (gate function + tests); the full SPY/SPX walk-forward run is deferred — it
> needs the market-data cache + compute (unavailable in this session), and SPY is already
> WFE-rejected (`engine/CLAUDE.md`), so any run is research/forward-test only, never a live
> path. Phase 4 deferred.

Phased, additive-only, smallest-first. Each phase is independently shippable and testable.
Nothing here touches `engine/config.py`, `engine/risk/`, or kill-switch code, so **no
`[safety-review]` tag required** — but adding any *new tradeable symbol* to live routing
remains gated by gate v2 + human approval (paper-only invariant unchanged).

### Phase 1 — Percentile VIX regime classifier (S, ~2-4hr)
- New module `engine/backtest/vix_percentile_regime.py`:
  - `classify_vix_regime(vix_series, lookback=252) -> Series[Crisis|HighVol|MidVol|LowVol]`
    using rolling percentile rank (point-in-time: percentile computed on bars <= t only,
    no full-series fit — enforce per `.claude/rules/testing.md`).
  - `momentum_overlay(price, window=63) -> Series[Bull|Neutral|Bear]`.
  - Returns a combined `RegimeContext`-style dataclass (vix_pctile, tier, momentum, confidence).
- Unit test `engine/tests/test_vix_percentile_regime.py` with known inputs->tiers and an
  explicit no-look-ahead assertion (decision at bar t unchanged when bars > t are mutated).
- Additive: does NOT modify `regime_classifier.py` or gate v2 wiring.

### Phase 2 — SPX & VIX instrument specs (S, ~1-2hr)
- Add to `engine/backtest/contract_specs.py`:
  - `SPX` (cash index, multiplier per chosen vehicle — XSP micro = $100, SPX = $100,
    confirm against the vehicle we'd actually trade), `VIX` (index, non-tradeable directly),
    `VX`/`VXM` (VIX futures) if we intend tradeable vol.
  - Decision needed from user: do we trade SPX via **options on SPY/XSP** (fits existing
    `engine/options/` + `options_backtester.py`) or via **index futures**? VIX is not
    directly tradeable — exposure is via VX futures or VIX options.
- Wire SPY/SPX into the existing trend + regime backtest runners (they already accept a
  symbol param).

### Phase 3 — VIX-conditioned trend backtests for SPY/SPX (M, ~3-6hr)
- Reuse `engine/backtest/trend_signals.py` + Phase 1 regime as an entry gate
  (e.g., suppress longs in Crisis tier, size up in LowVol/Bull). Pattern already proven
  for MES via `run_mes_trend_vix_rank1.py`.
- Run walk-forward (`run_walk_forward.py`) + Monte Carlo + deflated Sharpe; register any
  survivor in `candidate_registry.json` with a frozen hypothesis (do NOT route live —
  forward-test only, per the registry's design).

### Phase 4 (defer) — Dashboard regime card
- After Phase 1 ships and produces live values, add a regime widget to the dashboard using
  `fetchEngine` + existing badge variants.

## License & attribution

- **AgentQuant has no LICENSE file** -> treat as proprietary. We implement the *ideas*
  (percentile regime, momentum overlay) from scratch; **copy no code**. Attribute the
  concept in the new module's header comment and in the commit body.
- investing-algorithm-framework tutorial: concepts only, all already independently built.

## Effort estimate

- Phase 1: **S** (<4hr) — highest value/effort ratio, ship first.
- Phase 2: **S** (needs one user decision on the SPX/VIX vehicle).
- Phase 3: **M** (2-8hr, mostly compute + verdict review).
- Phase 4: **defer**.
- Total to a forward-testable SPY/SPX VIX-conditioned candidate: **M**.

## Red flags

- **No license on AgentQuant** — ideas-only boundary is strict.
- **VIX is not directly tradeable** — any "trade VIX" plan must resolve to VX futures or
  VIX/SPX options; needs a user decision before Phase 2.
- **Adding symbols != authorizing live trading** — paper-only + human-approval invariants
  hold; new symbols enter forward-test via the frozen candidate registry, not live routing.
- **Don't displace existing regime/gate machinery** — the percentile classifier is an
  additive second lens, not a replacement for `regime_classifier.py` (which gate v2 depends on).
