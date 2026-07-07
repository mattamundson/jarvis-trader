# Key Files Reference

| File | Purpose |
|------|---------|
| `engine/main.py` | FastAPI app, routes dispatched to 26 routers (90+ endpoints) |
| `engine/routers/` | 26 router files organizing 90+ API endpoints |
| `engine/config.py` | `TradingConfig` — all risk parameters (**Tier 3 to change**) |
| `engine/agents/pipeline.py` | 5-stage trading pipeline orchestrator |
| `engine/risk/safety_layer.py` | Kill switch, hard limits, order validation (**Tier 3 to change**) |
| `engine/backtest/signals.py` | STC signal logic — CANONICAL parameter source (**Tier 3 to change**) |
| `engine/orchestrator/multi_market.py` | Multi-market orchestrator (futures, options, crypto) |
| `engine/learning/` | Learning system — 4 modules (events, feedback, patterns, recommendations) |
| `engine/strategies/rl_agent.py` | RL trading agent (PPO, MES only, experimental) |
| `engine/strategies/rl_environment.py` | Gym trading environment (19 features from signals.py) |
| `engine/strategies/rl_trainer.py` | RL training loop (max_episode_bars=500) |
| `dashboard/lib/api.ts` | `fetchEngine`/`postEngine` — ALL dashboard API calls go here |
| `dashboard/app/layout.tsx` | Root Next.js layout, providers, sidebar |
| `docs/strategy/TRADING_RULES.md` | Formal entry/exit, sizing, regime layers, session policy |
| `docs/strategy/EQUATIONS.md` | Math reference aligned to signals.py / composite_signals.py |
