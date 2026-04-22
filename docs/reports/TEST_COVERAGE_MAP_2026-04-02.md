# Test Coverage Map — JARVIS TRADER
**Generated**: 2026-04-02
**Test Suite**: 39 test files, 19 modules under test (44% coverage by module count)

---

## Summary

| Metric | Value |
|--------|-------|
| **Test Files** | 39 test files in `engine/tests/` |
| **Modules Tested** | 19/43 top-level modules (44%) |
| **Module Test Density** | Critical path fully covered; experimental low |
| **Sacred Tests** | `test_safety_layer.py` (pass required), `test_integration.py` (28 tests) |
| **Coverage Gap** | 24 untested modules, mostly analytics/notifications/utils |

---

## Tested Modules (19 tested)

### CRITICAL Path (Safety & Execution)

| Module | Test Files | Key Coverage |
|--------|-----------|--------------|
| **risk** | `test_safety_layer.py`, `test_loss_tracker.py`, `test_tilt_detector.py`, `test_allow_paper_simulated_gating.py` | Kill switch, daily loss halt, drawdown halt, order validation (all 14 hard rules) |
| **execution** | `test_ib_gateway_connector_safety_wiring.py`, `test_ib_gateway_connector_offline.py` | IB Gateway paper routing, safety layer wiring, port 4002 paper mode |

### HIGH Priority (Core Pipeline)

| Module | Test Files | Key Coverage |
|--------|-----------|--------------|
| **agents** | `test_pipeline_e2e.py`, `test_task_board.py` | TradingPipeline 5-stage orchestration, BullResearcher/BearResearcher debate, task board |
| **routers** | `test_routes_wired.py`, `test_config_router.py`, `test_prices_router.py` (4 tests) | 80+ API endpoints wired, config routes, price endpoints |

### MEDIUM Priority (Markets & Data)

| Module | Test Files | Key Coverage |
|--------|-----------|--------------|
| **markets** | `test_market_modules.py` | FuturesMarketModule, OptionsMarketModule, CryptoMarketModule, PolymarketModule ABC compliance |
| **backtest** | `test_signals.py`, `test_rolling_wfe.py` | STC signal generation (OS=15, OB=83), rolling walk-forward engine |
| **data** | `test_price_cache.py` | Price caching, market data retrieval |
| **portfolio** | `test_portfolio_paper_trade_post.py`, `test_integration.py` | Portfolio tracking, position management, P&L |
| **database** | `test_integration.py` | SQLite persistence, migrations, schema |

### LOWER Priority (Infrastructure & Learning)

| Module | Test Files | Key Coverage |
|--------|-----------|--------------|
| **learning** | `test_learning.py`, `test_discord_learning.py`, `test_consolidator.py` | Pattern extraction, session memory, strategy tuning, consolidation |
| **llm** | `test_llm_client.py`, `test_context_manager.py` | Anthropic Claude API client, context window management |
| **kairos** | `test_kairos.py` | Dream daemon, observation logging, watchers (regime, tilt, correlation) |
| **orchestrator** | `test_orchestrator.py`, `test_foundation.py` | Capital allocator, correlation monitor, multi-market |
| **middleware** | `test_exception_handler.py`, `test_auth_and_rate_limit.py`, `test_cold_start_degraded.py` | Exception handling, rate limiting, auth, degraded startup |
| **paper** | `test_paper_validation.py` | Paper trading validation tracker |
| **discord** | `test_discord_learning.py` | Discord sentiment parsing, signal context, learning integration |
| **hooks** | `test_foundation.py` | React hooks registry, trading hooks state management |
| **flags** | `test_feature_flags.py` | Feature flag registry, runtime toggling |
| **strategies** | `test_rl_module.py` | RL trading agent (PPO), TradingEnvironment, evaluator |

---

## Untested Modules (24 untested, by risk level)

### CRITICAL Gap (Must Address)

**None** — All critical/high-priority modules have test coverage.

### MEDIUM Gap (Should Address)

| Module | Status | Why Untested | Suggested Tests |
|--------|--------|--------------|-----------------|
| **schedulers** | Untested | EOD scheduler, validation checker not mocked | Mock APScheduler, test scheduler lifecycle |
| **analytics** | Untested | Multi-timeframe analysis, VIX overlay | Test MTF confirmation, regime filtering |
| **cache** | Untested | Feature store, signal cache, Redis client | Test cache hits/misses, TTL eviction |
| **notifications** | Untested | Telegram/WhatsApp alerting | Mock external APIs, test message queuing |
| **options** | Untested | Options chain fetcher, greeks monitor, premium calc | Mock options data, test strategy executor |

### LOW Gap (Nice-to-Have)

| Module | Status | Why Untested |
|--------|--------|--------------|
| **analysis** | Untested | Discord correlation, time patterns (experimental) |
| **api** | Untested | API models / response schemas |
| **config.py** | Untested | TradingConfig, Pydantic validation |
| **dependencies.py** | Untested | FastAPI dependency injection |
| **health_monitor.py** | Untested | System health probes |
| **monitoring** | Untested | Prometheus metrics export |
| **security** | Untested | Log sanitization (has basic test coverage) |
| **speculation** | Untested | Speculation engine, prefetch cache |
| **utils** | Untested | Position sizing helpers |
| **websocket** | Untested | WebSocket event manager |
| **scripts/** | Untested | CLI scripts (init_capital, daily_health_check, etc.) — tested manually |
| **add_response_models.py** | Untested | Setup script |
| **update_main.py** | Untested | Setup script |
| **main.py** | Untested | FastAPI app bootstrap (covered by integration tests) |

---

## Recommended Next Tests (Priority Order)

### Top 5 for Phase 2 Hardening

1. **test_schedulers.py** (MEDIUM priority)
   - Test EOD scheduler lifecycle (startup, execute, cleanup)
   - Mock APScheduler; verify validation_checker runs on schedule
   - Suggested test cases: schedule fire, reschedule, exception recovery

2. **test_analytics.py** (MEDIUM priority)
   - Test MTF analyzer regime confirmation (5-layer filter)
   - Test VIX overlay spike detection (>20 percentile)
   - Suggested test cases: bullish MTF confirm, bearish VIX spike, no signal

3. **test_cache.py** (MEDIUM priority)
   - Test feature store read/write, TTL eviction
   - Test signal cache hit rate
   - Mock Redis; verify fallback to in-memory
   - Suggested test cases: cache hit, cache miss, eviction

4. **test_config.py** (LOW priority)
   - Test TradingConfig Pydantic validation
   - Test config defaults, overrides, env vars
   - Suggested test cases: valid config, invalid config, env override

5. **test_options.py** (MEDIUM priority)
   - Test options chain fetcher (mock yfinance)
   - Test greeks monitor (delta/gamma/theta decay)
   - Test premium calculator (Black-Scholes)
   - Suggested test cases: OTM chain, ATM chain, theta decay

---

## Test Files by Category

### Critical Safety Tests (Never skip)
- `test_safety_layer.py` — 14 hard rules validation ✓ REQUIRED
- `test_ib_gateway_connector_safety_wiring.py` — IB Gateway safety contract ✓ REQUIRED

### Integration & E2E Tests
- `test_integration.py` — 28 tests, Phase 1-2 coverage ✓ REQUIRED
- `test_pipeline_e2e.py` — Multi-agent orchestration
- `test_paper_validation.py` — 30-day validation tracker

### Router & API Tests
- `test_routes_wired.py` — All 80+ endpoints registered
- `test_api_contract_minimal.py` — API response schemas
- `test_config_router.py`, `test_prices_router.py` — Specific routers

### Market & Execution Tests
- `test_market_modules.py` — Futures/Options/Crypto/Polymarket
- `test_ib_gateway_connector_offline.py` — IB paper mode
- `test_rl_module.py` — RL agent (MES only, experimental)

### Data & Analysis Tests
- `test_signals.py` — STC oscillator (OS=15, OB=83) ✓ CANONICAL
- `test_price_cache.py` — Market data caching
- `test_rolling_wfe.py` — Walk-forward optimization

### Learning & Intelligence Tests
- `test_learning.py` — Pattern extractor, session memory
- `test_discord_learning.py` — Discord sentiment learning
- `test_consolidator.py` — Trade memory consolidation
- `test_kairos.py` — Dream daemon + watchers
- `test_llm_client.py` — Anthropic LLM calls

### Infrastructure Tests
- `test_feature_flags.py` — Feature flag registry
- `test_exception_handler.py` — Global exception handler
- `test_auth_and_rate_limit.py` — Rate limiter (slowapi)
- `test_cold_start_degraded.py` — Cold start resilience
- `test_foundation.py` — Hooks + capital allocator

### Special / Contract Tests
- `test_p0_verify_mirror.py` — Paper trade log mirroring
- `test_session4_contract.py` — Contract validation
- `test_paper_runner_engine_sync.py` — Paper runner sync

---

## Running Tests

```bash
# Full suite (required before PR)
cd engine && python -m pytest tests/ -v

# Sacred tests (never skip)
cd engine && python -m pytest tests/test_safety_layer.py -v

# Integration tests (28 tests)
cd engine && python -m pytest tests/test_integration.py -v

# Specific module
cd engine && python -m pytest tests/test_signals.py -v
```

---

## Coverage Gaps Summary

**Covered:** 19/43 modules (44%)
- All critical safety modules ✓
- All core pipeline modules ✓
- Most market/data modules ✓

**Gaps:** 24 untested modules
- 5 MEDIUM priority (schedulers, analytics, cache, notifications, options)
- 19 LOW priority (mostly analytics, utils, scripts, setup helpers)

**Recommendation:** Focus Phase 2 hardening on the 5 MEDIUM-priority modules before live trading gate. Low-priority modules can be covered during Phase 3 live deployment.

---

*Last Updated*: 2026-04-02
*Responsible*: Agent 1 (US-401 / Test Coverage Analysis)
