---
repo: dtquocbao/ai-market
url: https://github.com/dtquocbao/ai-market
stars: 369
language: Python (82.9%), TypeScript (9.4%)
license: MIT
archived: false
pushed_at: 2026-06 (active, exact date not captured)
analyzed_at: 2026-06-24
recommendation: defer
surfaces_with_value: [engine]
---

# dtquocbao/ai-market

## Core value proposition
An enterprise-styled multi-agent equity-analysis system: 10 specialized agents
(Momentum, Sentiment, Correlation, Risk, Volatility, Volume, EventImpact, Forecast,
Strategy, Meta) over a FastAPI + PostgreSQL/pgVector backend with an Angular
frontend. It bundles technical indicators, regime detection, VaR, portfolio
optimization, RL (PPO) strategy tuning, latent pattern detection, and an A/B testing
framework. Architecturally it is a parallel of jarvis-trader, built for equities.

## Surface analysis

### 1. Engine code
`partial-integrate` (mostly `dedup`) — Near-complete overlap with existing engine,
usually at lower maturity here:
- 10 agents → `engine/agents/` (debate, bull/bear researchers, risk_manager,
  fund_manager, technical/fundamental/news/social/options analysts).
- Regime detection (5 types) → `engine/analytics/regime_detector.py`,
  `intraday_regime.py`, `vix_overlay.py`.
- Ensemble signal blending → `engine/analytics/ic_ensemble.py` (IC-weighted).
- Backtest + Monte Carlo → `engine/backtest/`, `monte_carlo.py`,
  `engine/analytics/permutation_test.py` (MCPT).
- Portfolio optimization (Equal/MinVar/MaxSharpe/Risk-Parity) →
  `engine/portfolio/`, `risk_attribution.py`.
- Meta-evaluation agent → `engine/analytics/agent_feedback.py`,
  `performance_evaluator.py`.

**The one genuine gap:** latent pattern detection (PCA / Autoencoder / t-SNE / UMAP
embeddings for unsupervised regime/pattern clustering). A grep of the whole engine
returns zero hits — this concept is absent. Their RL/PPO strategy optimizer is a
softer gap (jarvis has `engine/data/rl_experiments/` started but immature).

### 2. Project rules
`no-fit`

### 3. Project skills
`no-fit`

### 4. Slash commands
`no-fit`

### 5. Subagents
`no-fit`

### 6. Docs
`no-fit`

### 7. Dev tooling
`no-fit` — Different stack (Angular + pgVector + Docker Compose); no transferable
CI/hook/PM2 pattern.

### 8. Dashboard
`no-fit` — Angular 17; jarvis dashboard is Next.js App Router. No reuse.

### 9. Ops / messaging
`no-fit`

## Integration plan
Only one surface carries value, and it is `defer`, not `integrate-now`:

- **Latent embedding regime/pattern clustering** — concept only, not code.
  Candidate home: `engine/analytics/` (e.g. a `latent_regime.py` that fits an
  embedding on point-in-time bar/feature windows and clusters them).
  Prerequisites before any code:
  1. A clear hypothesis for what the embedding buys over existing
     `regime_detector.py` — do not add a 6th regime tool just because it is novel.
  2. Strict point-in-time discipline (`testing.md` no-look-ahead): unsupervised
     `.fit()` must run only on in-sample windows, never the full series.
  3. An MCPT gate (`engine/analytics/permutation_test.py`) before promotion —
     embeddings on a 2-instrument account are a curve-fitting magnet.
  Do NOT lift their equity-fitted implementation; re-derive for micro-futures bars.

## License & attribution
MIT — if the latent-clustering idea is ever built, credit dtquocbao/ai-market in the
file header and commit body. No code is copied at proposal stage.

## Effort estimate
L (1-3 days) for a properly point-in-time, MCPT-gated latent-regime prototype.
Everything else is dedup (effort 0 — already shipped).

## Red flags
- Equity-oriented (Yahoo Finance, single-name stocks); a futures port is required,
  not a drop-in.
- The novel pieces (latent embeddings, PPO) are the highest curve-fit risk on a
  $10K, 2-instrument account — exactly where overfitting is cheapest and most
  dangerous.
- Importing more agents/indicators here would deepen the existing breadth-over-depth
  problem (see diagnostic in chat), not fix it.

## Reconsider-if
Build the latent-regime prototype only once a single existing strategy has cleared
its WFE + MCPT gate live — i.e. when there is a validated base to differentiate, not
before.
