# Capability matrix

**Audience:** Engineering + product judgment.  
**Maturity legend:**

| Label | Meaning |
|-------|---------|
| **ProdPaper** | Intended for daily paper operations; backed by tests/runbooks for critical path |
| **Beta** | Works in happy path; edge cases or ops gaps remain |
| **Experimental** | Code present; not a dependency for validated paper trading |
| **Dormant** | Stub, partial mount, or explicitly disabled — verify before investing |

**Note:** This matrix is **judgmental**, not generated from code. Reconcile with tests and runbooks before changing labels.

---

## Core trading loop

| Capability | Maturity | Primary code / API | Notes |
|------------|----------|-------------------|--------|
| 5-stage LLM pipeline | ProdPaper | [engine/agents/pipeline.py](../../engine/agents/pipeline.py), [engine/routers/pipeline_router.py](../../engine/routers/pipeline_router.py) | Billing/latency dependency |
| Safety layer / kill switch | ProdPaper | [engine/risk/safety_layer.py](../../engine/risk/safety_layer.py), [engine/routers/safety_router.py](../../engine/routers/safety_router.py) | Tier 3; non-LLM |
| Human approval flow | ProdPaper | [engine/routers/approval_router.py](../../engine/routers/approval_router.py), approval modules | `REQUIRE_HUMAN_APPROVAL` |
| Paper validation / gates | Beta | [engine/routers/paper_validation_router.py](../../engine/routers/paper_validation_router.py), [engine/paper/](../../engine/paper/) | Align with WFE docs |
| Order routing / execution | Beta | [engine/execution/](../../engine/execution/) | IB/Schwab paths; verify env |

---

## Market coverage

| Capability | Maturity | Primary code | Notes |
|------------|----------|--------------|--------|
| Futures (MES/MGC focus) | ProdPaper | [engine/markets/futures/](../../engine/markets/futures/), orchestrator | Validated symbols only for “real” paper (MES/MGC active; MCL/MNQ halted) |
| Options | Experimental / Beta | [engine/markets/options/](../../engine/markets/options/), [engine/options/](../../engine/options/) | Infrastructure exists; activation depends on broker/data |
| Crypto | Experimental | [engine/markets/crypto/](../../engine/markets/crypto/) | Often disabled by default |
| Polymarket | Experimental | [engine/markets/polymarket/](../../engine/markets/polymarket/), [engine/routers/polymarket_router.py](../../engine/routers/polymarket_router.py) | Stub/adjacent |

---

## Analysis, backtest, research

| Capability | Maturity | Primary code | Notes |
|------------|----------|--------------|--------|
| STC / canonical signals | ProdPaper (params Tier 3) | [engine/backtest/signals.py](../../engine/backtest/signals.py) | Changes require approval |
| Backtest / walk-forward | Beta | [engine/backtest/](../../engine/backtest/) | WFE discipline required |
| WFE reporting API | Beta | [engine/routers/wfe_router.py](../../engine/routers/wfe_router.py) | Dashboard consumption |
| RL / strategy experiments | Experimental | [engine/strategies/](../../engine/strategies/), related routers | Do not conflate with validated paper |
| Hidden pivots | Beta / Experimental | [engine/routers/hidden_pivots_router.py](../../engine/routers/hidden_pivots_router.py) | Feature-specific |

---

## Learning and observability

| Capability | Maturity | Primary code | Notes |
|------------|----------|--------------|--------|
| Events bus | Beta | [engine/events/](../../engine/events/), [engine/routers/events_router.py](../../engine/routers/events_router.py) | Foundation for audit |
| Learning modules | Experimental | [engine/learning/](../../engine/learning/) | Consolidate vs stubs per audit |
| Prometheus / metrics | Beta | Metrics hooks across engine | Grafana compose in infra |
| Pipeline profiling | Beta | [engine/profiling/](../../engine/profiling/), [engine/routers/profiling_router.py](../../engine/routers/profiling_router.py) | Cost/latency insight |

---

## Integrations and notifications

| Capability | Maturity | Primary code | Notes |
|------------|----------|--------------|--------|
| Discord | Beta | [engine/routers/discord_router.py](../../engine/routers/discord_router.py), [engine/discord/](../../engine/discord/) | Prompt-injection tests exist |
| WhatsApp / Twilio | Beta | [engine/notifications/](../../engine/notifications/) | Env-sensitive |
| OpenClaw | Beta | Notifiers / troubleshooting | See [docs/troubleshooting.md](../troubleshooting.md) |
| Schwab | Beta | [engine/execution/schwab_connector.py](../../engine/execution/schwab_connector.py), [engine/routers/schwab_router.py](../../engine/routers/schwab_router.py) | OAuth and policy |
| ThinkScript export | Experimental | [engine/routers/thinkscript_router.py](../../engine/routers/thinkscript_router.py) | Adjacent to TOS workflow |

---

## Dashboard

| Capability | Maturity | Primary code | Notes |
|------------|----------|--------------|--------|
| Engine API client | ProdPaper | [dashboard/lib/api.ts](../../dashboard/lib/api.ts) | No hardcoded `localhost:8010` |
| Command / risk / pipeline pages | Beta | [dashboard/app/](../../dashboard/app/) | Build: `pnpm run build` |
| WebSocket client | Beta | [dashboard/hooks/](../../dashboard/hooks/) | Align with engine WS |

---

## When this matrix conflicts with canon

**Unified Canon wins** for narrative and research-truth policy. **validated-instruments** wins for symbol approval. Update this file when you intentionally promote or demote a capability.
