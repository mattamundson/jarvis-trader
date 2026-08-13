# RL Bug & Test Registry — Session 2026-04-02

**Generated**: 2026-04-02
**Source**: `RL_SESSION_2026-04-02.md` + `engine/strategies/test_rl_env.py`
**Final counts**: 37 unique bug fixes | 84 unit tests | 9 training runs documented

---

## Section 1: Complete Bug Fix Registry (37 fixes)

### Core Reward Function Fixes (Session Start — Bugs #1–#6)

| Fix # | File | Bug Description | Fix Applied |
|-------|------|-----------------|-------------|
| **#1** | `engine/strategies/rl_environment.py` → `_calculate_reward()` | **Compounding hold_cost**: `hold_cost = hold_cost_per_bar * bars_in_trade` grew quadratically. After 50 bars: -0.001 × (1+2+…+50) = **-1.275** total cost, exceeding any possible profit. Caused agent to BUY-spam (59.4% BUY, hold_rate=16.5%). | Changed to flat: `hold_cost = hold_cost_per_bar` (not multiplied by bars_in_trade) |
| **#2** | `engine/strategies/rl_environment.py` → `step()` + `_calculate_reward()` | **Free redundant BUY exploit**: BUY when already long was a complete no-op — no position change, no entry_cost. Agent discovered this as a "free HOLD" and spammed BUY. | Added `redundant_cost = entry_cost` for BUY-when-long / SELL-when-short |
| **#3** | `engine/strategies/rl_environment.py` → `_calculate_reward()` | **Double-penalty on new entries** (found by Agent 5): `step()` updates `self._position` (0→1) BEFORE calling `_calculate_reward()`, so BUY-when-long check was True for genuine new entries too → `-0.20 × 2 = -0.40` on every new entry. | Added `not is_new_entry` guard to `redundant_cost` check |
| **#4** | `engine/routers/health_router.py` (lines 70, 314) | **`is_connected()` called as method**: `IBKRDataConnector.is_connected` is a `@property` (returns bool), not a method. `is_connected()` call caused HTTP 500 on every `GET /health` after engine restart. Linter kept reverting fix; re-applied manually each time. | Line 70: `data_manager.ibkr.is_connected()` → `bool(data_manager.ibkr.is_connected)`. Line 314: `getattr(ib_gw, "is_connected", lambda: False)()` → `bool(getattr(ib_gw, "is_connected", False))` |
| **#5** | `engine/strategies/rl_trainer.py` | **yfinance 730-day limit for 1h data**: `TRAIN_LOOKBACK_DAYS = 1460` was clamped to 730 days, but yfinance returns empty for 1h data with `period=730d`. Caused "Insufficient data for MES: got 0 bars" on second training run. | Cache-first loading: skip `yfinance` entirely when parquet cache exists; only call yfinance on cold path |
| **#6** | `engine/strategies/rl_config.py` | **Missing VALIDATION_GATES keys** (found by Agent 5): `VALIDATION_GATES` was missing `min_trades`, `min_hold_rate`, `max_drawdown`. Caused 2 of 40 unit tests to fail. | Added `"min_trades": 60`, `"max_drawdown": 0.15`, `"min_hold_rate": 0.50` to `VALIDATION_GATES` dict |

---

### Training Infrastructure Fixes (Bugs #7 — from agent fix numbering)

| Fix # | File | Bug Description | Fix Applied |
|-------|------|-----------------|-------------|
| **#7** | `engine/strategies/rl_environment.py` | **`prepare_dataframe()` signature**: Did not accept `df=None` — cache-only load path broke when called without raw data. | Updated `prepare_dataframe()` signature to accept `df=None` when loading from parquet cache |

---

### Executor Fixes — Agent 2 (Bugs #8–#11)

| Fix # | File | Bug Description | Fix Applied |
|-------|------|-----------------|-------------|
| **#8** | `engine/strategies/rl_executor.py` | **`asyncio.get_event_loop()` deprecated**: Use of deprecated API that raises `DeprecationWarning` and fails in async contexts. | Changed to `get_running_loop()` with `RuntimeError` fallback |
| **#9** | `engine/strategies/rl_executor.py` | **Double `compute_all_indicators()` call**: `_compute_obs()` called `compute_all_indicators()` internally but the caller also called it, processing indicators twice per cycle. | Changed `_compute_obs()` to return `(obs, df_ind)` tuple, eliminating the double computation |
| **#10** | `engine/strategies/rl_executor.py` | **Thread-unsafe executor registry**: `_executor_registry` dict was mutated from multiple threads without synchronization, risking race conditions. | Added `threading.Lock()` for all mutations to `_executor_registry` |
| **#11** | `engine/strategies/rl_executor.py` | **Missing `scheduler_running` field**: `get_status()` did not include `scheduler_running` in its output dict, causing dashboard to display incomplete status. | Added `scheduler_running` to `get_status()` output |

---

### Walk-Forward Fixes — Agent 3 (Bugs #12–#15)

| Fix # | File | Bug Description | Fix Applied |
|-------|------|-----------------|-------------|
| **#12** | `engine/strategies/rl_trainer.py` | **Wrong walk-forward validation gate key**: Used non-existent `sharpe` key in per-window gate check → `KeyError` at runtime. | Changed gate check to use documented keys: `max_drawdown` + `n_trades` |
| **#13** | `engine/strategies/rl_trainer.py` | **Cache ignored in walk-forward training**: `train_walkforward()` always fetched from yfinance even when parquet cache existed. | Added cache-first check inside `train_walkforward()` |
| **#14** | `engine/routers/strategies_router.py` | **Walk-forward results endpoint missing fields**: Response was missing `windows`, `all_pass`, `pass_rate`, `aggregate_metrics`, `best_model_path`, `recommendation`, `n_windows` fields. | Added all 7 missing fields to the walk-forward results response |
| **#15** | `engine/strategies/rl_environment.py` → `build_env()` | **Dead code in `build_env()`**: Stray `return df_processed` statement in `build_env()` — unreachable dead code that could confuse static analysis. | Removed stray `return df_processed` |

---

### API / Health Endpoint Fixes — Agents 4C, 4D (Bugs #16–#19)

| Fix # | File | Bug Description | Fix Applied |
|-------|------|-----------------|-------------|
| **#16** | `engine/strategies/rl_trainer.py` | **`list_models()` missing return statement**: Function completed execution without returning `results`, causing caller to receive `None` → HTTP 500 on `GET /strategies/rl/models`. | Added `return results` at end of `list_models()` |
| **#17** | `engine/routers/health_router.py` | **Preflight bare `return` → null body**: Health preflight function had bare `return` statement producing null HTTP body, failing JSON parsing in clients. | Changed to `return {"all_pass": all_pass, "checks": checks}` |
| **#18** | `engine/risk/pnl_monitor.py`, `engine/main.py`, `engine/config.py` | **`PnLMonitor` starting_balance=0.0**: Monitor was initialized with zero balance, generating false drawdown alarms from the first tick. | Added `starting_balance` parameter to `PnLMonitor.__init__()` with $10,000 fallback |
| **#19** | `engine/data/market_data.py` | **`IBKRDataConnector` missing `health_check()` method**: Health endpoint tried to call `ibkr.health_check()` which didn't exist → `AttributeError`. | Added `async health_check()` method to `IBKRDataConnector` |

---

### Metrics Quality Fixes — Agents 5B, 3D (Bugs #20–#22)

| Fix # | File | Bug Description | Fix Applied |
|-------|------|-----------------|-------------|
| **#20** | `engine/strategies/rl_environment.py` | **Blended `hold_rate` metric was misleading**: `hold_rate` counted ALL HOLD actions including those taken while in a position, trivially inflating the metric. Example: 60 trades × 10 bars = 600 in-position HOLD + 610 flat HOLD = 95% hold_rate with no discriminative value. | Added `_bars_flat` and `_hold_when_flat` counters. New metric `flat_hold_rate` = HOLD actions when flat / total flat bars |
| **#21** | `engine/strategies/rl_agent.py` | **`evaluate()` key union bug**: Aggregation used `all_metrics[0].keys()` so any key absent from the first episode dict was silently dropped from aggregate. | Changed to `set().union(*[m.keys() for m in all_metrics])` — union of all episode keys |
| **#22** | `engine/strategies/rl_config.py` | **Misleading comment in `rl_config.py`**: Comment stated "~333 HOLD bars ≈ 1 ATR of entry cost recovered" which was mathematically wrong. Correct math: `entry_cost(-0.10) / flat_hold_reward(0.003)` = 33 bars break-even, not 333. | Fixed comment to "33 bars break-even" |

---

### Dashboard Fix — Agents 4, 6B (Bug #23)

| Fix # | File | Bug Description | Fix Applied |
|-------|------|-----------------|-------------|
| **#23** | `dashboard/app/strategies/page.tsx` | **`flat_hold_rate` missing from dashboard**: New `flat_hold_rate` metric was added to the engine but not reflected in the dashboard `Metrics` TypeScript type, metrics grid, or `ValidationGatesPanel`. | Added `flat_hold_rate` to `Metrics` type, metrics grid, and `ValidationGatesPanel` |

---

### Episode Length / Training Volume Fix (Bug #24–#25)

| Fix # | File | Bug Description | Fix Applied |
|-------|------|-----------------|-------------|
| **#24** | `engine/strategies/rl_agent.py` | **`passes_validation()` missing hold_rate gate**: Gate function evaluated profit_factor, sharpe, win_rate, max_drawdown, n_trades but not `hold_rate` — a key gate metric. | Added `hold_rate >= gates["min_hold_rate"]` check to `passes_validation()` |
| **#25** | `engine/strategies/rl_environment.py`, `rl_config.py`, `rl_trainer.py`, `test_rl_env.py` | **Episode length too long → insufficient training episodes**: Without `max_episode_bars`, each episode = full dataset (~12,340 bars). 500k timesteps / 12,340 bars ≈ only **24 complete training episodes** — too few for PPO to converge. Agent overfits to HOLD-flat (earning +0.003/bar × 12,340 = +37 reward per episode) and trades only 14 times. | Added `max_episode_bars: int = 500` param to `TradingEnvironment.__init__()`. Episodes now randomly windowed (500-bar windows). 500k / 500 = ~1,000 diverse training episodes. Added `MAX_EPISODE_BARS = 500` constant to `rl_config.py`. Added `+6 tests` in `TestMaxEpisodeBars` class. |

---

### Bugs Found During Runs 6–7 (Bugs #26–#27)

| Fix # | File | Bug Description | Fix Applied |
|-------|------|-----------------|-------------|
| **#26** | `engine/main.py` | **`strategies_router` not mounted**: All `/strategies/*` routes returned HTTP 404. Root cause: `strategies_router` was never added to the FastAPI app via `app.include_router()`. | Added `app.include_router(strategies_router)` to `engine/main.py`; engine restarted |
| **#27** | `engine/strategies/rl_config.py` | **`flat_hold_reward` making trade count worse**: Increasing flat patience reward (0.003→0.005) was counterproductive — higher reward for staying flat raises the opportunity cost of entering any trade. Run 5→6: n_trades stayed at 14→11. | Removed `flat_hold_reward` entirely (set to 0.000) — Scenario C config |

---

### Wave 5–6 Bugs (Bugs #28–#33)

| Fix # | File | Bug Description | Fix Applied |
|-------|------|-----------------|-------------|
| **#28** | `engine/main.py` | **10 additional routers not mounted**: Full audit after Bug #26 revealed websocket_router, webhook_router, crypto_router, polymarket_router, and 6 other multi-market routers were also not wired into the FastAPI app. | Systematically added all missing `app.include_router()` calls; now 26/26 routers mounted |
| **#29** | `engine/risk/pnl_monitor.py` | **`starting_balance=None` from two independent code paths**: Two separate paths in `pnl_monitor.py` could return `starting_balance=0.0` or `None`, causing false drawdown alarms. | Fix 1: Seeded `_cached_state` with `starting_balance` at construction time. Fix 2: Added `_starting_balance` fallback in `_read_sqlite_today()` |
| **#30** | `engine/strategies/test_rl_env.py` | **`test_flat_hold_reward_is_positive` failing after Scenario C**: Test asserted `flat_hold_reward > 0` but Scenario C intentionally sets it to 0.000. | Changed assertion to `>= 0` to allow Scenario C=0.000 AND future positive values |
| **#31** | `engine/strategies/rl_executor.py` | **`next_fire_time` missing from executor `get_status()`**: Dashboard expected `next_fire_time` in executor status response, but field was absent → dashboard displayed broken status card. | Added `next_fire_time` from `self._scheduler.get_jobs()[0].next_run_time.isoformat()` with None fallback |
| **#32** | `engine/tests/test_integration_rl_endpoints.py`, `engine/routers/strategies_router.py` | **Integration tests using stale `/rl/...` paths**: Tests used compact paths (`/rl/status`, `/rl/health`, etc.) but router restructuring moved these to `/strategies/rl/...`. | Updated all `/rl/...` paths to `/strategies/rl/...`; added `GET /rl/health` to `strategies_router.py` |
| **#33** | `engine/routers/thinkscript_router.py` | **Bare top-level import in `thinkscript_router`**: Module had a bare top-level `import` that could raise `ImportError` at startup and crash all 26 routers from mounting. | Wrapped bare import in `try/except ImportError` block |

---

### Walk-Forward Gate + Test Fixes — Wave 8 (Bugs #34–#35)

| Fix # | File | Bug Description | Fix Applied |
|-------|------|-----------------|-------------|
| **#34** | `engine/strategies/rl_trainer.py` → `train_walkforward()` | **Walk-forward gate missing `hold_rate` check**: Per-window validation checked only 4/6 gates (profit_factor, win_rate, max_drawdown, n_trades). `hold_rate` gate was silently skipped. | Added `hold_rate >= gates["min_hold_rate"]` per-window check. Note: sharpe gate cannot be computed per-window (env doesn't output Sharpe) — known limitation. |
| **#35** | `engine/strategies/test_rl_env.py` → `TestWalkForward`, `engine/tests/test_integration_rl_endpoints.py`, `engine/scripts/live_engine_probe.py` | **`TestWalkForward` mocks missing `reward_config=None` kwarg**: 5 mock functions in `TestWalkForward` didn't accept `reward_config` keyword arg, causing `TypeError` when trainer passed it. Integration test paths also stale. | Added `reward_config=None` parameter to all 5 mock `_train_and_evaluate_window` functions; updated all stale endpoint paths |

---

### Wave 9 Fixes (Bug #36)

| Fix # | File | Bug Description | Fix Applied |
|-------|------|-----------------|-------------|
| **#36** | `/tmp/train_symbols_run7.sh`, `/tmp/eval_run7.py` | **Wrong API key in multi-symbol training script**: Scripts used `test-key` as API key. Engine requires `jarvis-dev-key-change-me`. All API calls were returning 401 Unauthorized, silently failing multi-symbol training. | Fixed API key from `test-key` → `jarvis-dev-key-change-me` in both scripts; `/tmp/eval_run7.py` recreated fresh |

---

### Wave 13 Fix (Bug #37)

| Fix # | File | Bug Description | Fix Applied |
|-------|------|-----------------|-------------|
| **#37** | `dashboard/app/strategies/page.tsx` → `WalkForwardGridPanel` (3 locations) | **Walk-forward panel missing `hold_rate` column**: `WalkForwardWindowMetricsGrid` interface, `WF_GRID_GATE_DEFS`, and results table all lacked `hold_rate`. Dashboard showed walk-forward windows without the key gate metric. | Added `hold_rate: number` to interface; added `hold_rate` gate def with ≥0.50 threshold; added Hold Rate column with green/red color coding |

---

### Wave 14–15 Fix (Bug #38)

| Fix # | File | Bug Description | Fix Applied |
|-------|------|-----------------|-------------|
| **#38** | `engine/routers/strategies_router.py`, `engine/strategies/rl_trainer.py` | **Stop endpoint missing from router** (noted during Wave 15 summary as Fix #38): No endpoint existed to abort an in-progress training run. Any long training run (47+ min) could not be cancelled without killing the engine process. | Implemented `POST /strategies/rl/stop` endpoint. Added `threading.Event` stop flag (`_stop_event`), `request_stop()`, `clear_stop()` module functions. Abort gate added before `PPO.learn()` in `train_symbol()` and at window boundaries in `train_walkforward()`. |

---

## Section 2: Test Class Breakdown (84 tests)

### File: `engine/strategies/test_rl_env.py`

| # | Class Name | Test Methods | Count |
|---|-----------|--------------|-------|
| 1 | `TestTradingEnvironmentReset` | `test_reset_returns_obs_and_info`, `test_obs_shape`, `test_obs_dtype`, `test_obs_no_nan`, `test_obs_no_inf`, `test_reset_resets_position`, `test_seed_reproducibility` | **7** |
| 2 | `TestTradingEnvironmentStep` | `test_step_returns_five_tuple`, `test_step_hold_from_flat`, `test_step_all_actions_valid_obs` (×4 parametrized), `test_step_buy_opens_long`, `test_step_sell_opens_short`, `test_step_close_from_flat_is_noop`, `test_step_close_closes_long`, `test_step_close_closes_short`, `test_step_terminates_at_end`, `test_entry_cost_applied_on_buy` | **12** |
| 3 | `TestPositionConstraints` | `test_buy_when_long_does_not_double`, `test_sell_when_short_does_not_double` | **2** |
| 4 | `TestObservationSpace` | `test_obs_space_shape`, `test_action_space_size`, `test_action_space_contains_all_actions` | **3** |
| 5 | `TestEpisodeMetrics` | `test_get_episode_metrics_structure`, `test_metrics_after_buy_close_cycle`, `test_t1_hit_rate_tracks_correctly` | **3** |
| 6 | `TestBuildEnv` | `test_build_env_returns_environment`, `test_build_env_reset_works` | **2** |
| 7 | `TestExtractFeatures` | `test_extract_features_shape`, `test_extract_features_dtype`, `test_extract_features_no_nan`, `test_extract_features_position_reflected`, `test_extract_features_first_bar` | **5** |
| 8 | `TestMultipleSymbols` | `test_env_step_all_symbols` (×4 parametrized: MES, MNQ, MCL, MGC) | **4** |
| 9 | `TestValidationGates` | `test_validation_gates_have_required_keys`, `test_validation_gates_values_in_range`, `test_min_hold_rate_gate_is_50_percent` | **3** |
| 10 | `TestRewardFunctionFixes` | `test_hold_cost_is_flat_not_compounding`, `test_hold_cost_accumulation_over_50_bars`, `test_redundant_buy_when_long_penalized`, `test_redundant_sell_when_short_penalized`, `test_normal_entry_penalized_once`, `test_hold_when_flat_gets_reward`, `test_hold_when_in_position_gets_hold_cost`, `test_hold_cost_is_negative_when_in_position`, `test_flat_hold_reward_is_non_negative`, `test_flat_hold_rate_tracked`, `test_flat_hold_rate_when_in_position` | **11** |
| 11 | `TestWalkForwardSkeleton` | `test_trainer_module_importable`, `test_trainer_class_exists`, `test_trainer_has_walkforward_method`, `test_trainer_has_train_symbol_method` | **4** |
| 12 | `TestWalkForward` | `test_walkforward_window_count`, `test_walkforward_cache_used`, `test_walkforward_gate_keys`, `test_walkforward_all_pass`, `test_walkforward_partial_fail` | **5** |
| 13 | `TestMaxEpisodeBars` | `test_episode_terminates_at_max_episode_bars`, `test_episode_start_is_random_across_resets`, `test_episode_end_within_dataset_bounds`, `test_small_df_runs_full_dataset`, `test_build_env_passes_max_episode_bars`, `test_default_max_episode_bars_is_500` | **6** |
| 14 | `TestEvaluateEpisodes` | `test_evaluate_seed_gives_different_starts`, `test_evaluate_full_test_always_starts_at_warmup`, `test_evaluate_aggregates_multiple_episodes` | **3** |
| 15 | `TestRewardConfigOverride` | `test_default_reward_config_is_used_when_none`, `test_reward_config_override_replaces_entry_cost`, `test_reward_config_override_multiple_keys`, `test_run7_scenario_a_values`, `test_build_env_forwards_reward_config` | **5** |
| 16 | `TestRLExecutor` | `test_executor_registry_starts_empty`, `test_get_executor_status_empty_registry`, `test_get_executor_status_with_mock_executor`, `test_executor_registry_is_dict`, `test_executor_registry_lock_exists` | **5** |
| 17 | `TestRLConfig` | `test_run8_two_lever_config_values`, `test_t1_bonus_to_entry_cost_ratio` | **2** |
| 18 | `TestRLTrainerStop` | `test_stop_event_exists_and_is_threading_event` | **1** |
| | **GRAND TOTAL** | | **84** |

### Test Count Progression During Session

| Milestone | Count | Notes |
|-----------|-------|-------|
| Prior session end | 38/40 | 2 failures in `TestValidationGates` |
| Early session (Bug #6 fix) | 40/40 | ValidationGates fixed |
| Wave 1 additions | 53/53 | +13 tests: `TestRewardFunctionFixes` (9) + `TestWalkForwardSkeleton` (4) |
| Wave 2 additions | 55/55 | +2 tests: `flat_hold_rate` tracking |
| Bug #25 fix (max_episode_bars) | 66/66 | +6 `TestMaxEpisodeBars` + 5 additional |
| Wave 3 additions | 74/74 | +5 `TestRewardConfigOverride` |
| Wave 9 additions | 79/79 | +5 `TestRLExecutor` |
| Wave 11 additions | 81/81 | +2 `TestRLConfig` regression guards |
| Wave 14 additions | 83/83 | +2 (`test_t1_hit_rate_tracks_correctly`, `test_t1_bonus_to_entry_cost_ratio`) |
| Wave 15 final | **84/84** | +1 `TestRLTrainerStop` |

---

## Section 3: Reward Tuning History (Runs 1–9)

### Run Configuration Summary

| Run | entry_cost | hold_cost_per_bar | flat_hold_reward | max_episode_bars | timesteps | n_trades | hold_rate | profit_factor | Decision |
|-----|-----------|-------------------|------------------|------------------|-----------|----------|-----------|---------------|----------|
| 1 | -0.02 (default) | -0.001 (compounding bug) | — | None (full dataset) | 10,000 | — | 28.9% | 0.09 | Baseline — entry_cost too low, compounding hold bug present |
| 2 | -0.05 | -0.001 (compounding bug) | — | None | 100,000 | — | 20.5% | 0.55 | Partial improvement — compounding bug still present |
| 3 | -0.20 | -0.001 (compounding bug) | 0.003 (added) | None | 500,000 | — | 16.5% | 0.85 | hold_rate got WORSE with entry_cost increase — compounding bug still present |
| 4 | -0.20 | **-0.001 flat** (Bug #1 fixed) | 0.003 | None | 500,000 | **14** | **77.87%** | 0.31 | Bug #1–3 fixes worked: hold_rate jumped from 16.5% → 77.87%. But n_trades=14 (need ≥60). Root: entry_cost=-0.20 over-penalized entries. → Reduce entry_cost |
| 5 | **-0.10** | -0.001 flat | 0.003 | None | 500,000 | **14** | 59.02% | 0.2952 | n_trades unchanged at 14. Root cause not entry_cost magnitude — it was episode count (Bug #25). Only ~24 episodes per run with full-dataset episodes. → Fix episode length |
| 6 | -0.10 | -0.001 flat | **0.005** (raised) | **500** (Bug #25 fixed) | 500,000 | **11** | 66.10% | 0.1392 | n_trades fell to 11 (worse). flat_hold_rate=0.000 — agent never holds when flat (always enters immediately). Raising flat_hold_reward raised opportunity cost of trading. → Apply Scenario C (remove flat_hold_reward) |
| 7 | **-0.05** | -0.001 flat | **0.000** (Scenario C) | 500 | 500,000 | **3** | 98.8% | 0.0547 | Over-corrected — agent learned pure HOLD-everything. entry_cost=-0.05 + no flat reward = agent never exits because break-even is 50 bars. → Two-Lever fix: raise hold_cost + cut entry_cost |
| 8 | **-0.02** (Two-Lever) | **-0.002** (Two-Lever) | 0.000 | 500 | 500,000 | _old config_ | — | — | Run 8 launched using OLD Scenario C config (engine had NO `--reload` flag). Config changes from Bug #25 fix did not take effect. This run was effectively a repeat of Run 7 configuration. → Restart engine → Run 9 |
| 9 | -0.02 (Two-Lever) | -0.002 (Two-Lever) | 0.000 | 500 | 500,000 | _pending_ | _pending_ | _pending_ | First true Two-Lever run after engine restart with correct config. Break-even: 10 bars (0.02 / 0.002). T1 bonus (0.10) = 5× entry cost (0.02). Prediction: 50–100 trades. |

### Two-Lever Reward Config (Run 9 — Final Session Config)

```python
REWARD_CONFIG = {
    "pnl_atr_weight":    1.0,
    "hold_cost_per_bar": -0.002,   # doubled from -0.001 — makes long holds expensive
    "entry_cost":        -0.02,    # quartered from -0.05 — dramatically lowers per-trade barrier
    "t1_bonus":           0.10,
    "flat_hold_reward":   0.000,   # pure P&L signal, no passive patience reward
}
# Break-even hold: abs(entry_cost) / abs(hold_cost_per_bar) = 0.02 / 0.002 = 10 bars
# T1 bonus / |entry_cost| ratio = 5.0 (monitor for T1-hunting behavior)
```

### Key Insight: The HOLD-Attractor Problem

Each reward configuration change explored one axis of the HOLD-attractor problem:

```
Runs 1–3:  Compounding hold_cost made trading impossible → BUY-spam
Run 4:     Fixed hold_cost, raised entry_cost → hold_rate=77% but n_trades=14
Runs 5–6:  Episode length (~24 episodes/run) → agent earns +37 flat reward per episode
           safe HOLD-flat always beats uncertain trading
Run 7:     Scenario C (no flat reward) → pure hold-in-position; 98.8% hold, 3 trades
Run 8:     Wrong config (engine no-reload) → wasted run
Run 9:     Two-Lever: 10-bar break-even forces ~50 trades/episode by incentive design
```

---

## Summary

| Metric | Value |
|--------|-------|
| Unique Fix # entries found | **37** (plus Fix #38 from Wave 15 = 38 total tracked) |
| Total unit tests extracted | **84** (84/84 passing at session end) |
| Training runs documented | **9** (Runs 1–9, Run 9 pending completion) |
| Integration tests at session end | 61 passed + 1 skipped |
| TypeScript errors at session end | 0 |
| Total routers mounted in main.py | 26/26 |
| New files created this session | `rl_executor.py` + 5 runbook docs |
| Waves completed | 16 |
