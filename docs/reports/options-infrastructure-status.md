# Options Infrastructure Status Report

**Date**: 2026-04-02
**Audited by**: Agent-8 (options-audit task)
**Scope**: `engine/options/` (6 files) + `engine/routers/options_router.py`

---

## File Inventory

### 1. `engine/options/__init__.py`
- **Purpose**: Package marker only (1 line, empty module comment)
- **Import status**: CLEAN — no imports at all
- **yfinance**: ABSENT
- **Wired in main.py**: N/A (package init)
- **Notes**: Minimal but correct. Could expose public API symbols via `__all__` for convenience.

---

### 2. `engine/options/chain_fetcher.py` (484 lines)
- **Purpose**: Fetches live options chain data via `MarketDataManager`/Polygon. Computes IV Rank from historical close-to-close volatility proxy. Provides delta-based filtering utilities (`filter_by_delta`, `find_strike_by_delta`). Falls back to `BacktestDataLoader` for IV Rank when `data_manager` is unavailable.
- **Import status**: CLEAN — all imports resolve successfully
  - Intra-package: `from .greeks_monitor import calculate_greeks, iv_rank` (lazy, inside functions)
  - External deps: `asyncio`, `pandas`, `math`, `datetime`, `logging` (all stdlib/standard)
  - Fallback: `from backtest.data_loader import BacktestDataLoader` (confirmed resolvable)
- **yfinance**: ABSENT — zero references
- **Wired in main.py**: YES (indirectly via `options_router.py` — see note below)
- **Notes**: File exceeds 400-line guideline (484 lines). Current chain data implementation returns an **empty** calls/puts list — the chain structure is built but no strike-level data is populated because a true live options chain source (Polygon options chain endpoint) is not yet integrated. IV Rank calculation is a **proxy** based on historical realized volatility, not actual ATM IV snapshots.

---

### 3. `engine/options/greeks_monitor.py` (466 lines)
- **Purpose**: Black-Scholes Greeks calculator (`calculate_greeks`), Newton-Raphson IV solver (`implied_volatility`), IV Rank/Percentile utilities (`iv_rank`, `iv_percentile`), portfolio-level Greeks aggregation (`PortfolioGreeks` dataclass), and `GreeksMonitor` class that tracks positions and fires `DELTA_BREACH` / `GAMMA_SPIKE` alerts.
- **Import status**: CLEAN — stdlib only at module level (`math`, `logging`, `dataclasses`, `datetime`, `typing`). Lazy import of `premium_calculator.black_scholes_price` inside `implied_volatility()` to avoid circular import.
- **yfinance**: ABSENT
- **Wired in main.py**: YES (indirectly via `options_router.py` and `position_manager.py`)
- **Notes**: Self-contained Black-Scholes implementation. No external dependencies. File is 466 lines — slightly above the 400-line guideline but under the 800-line hard limit.

---

### 4. `engine/options/position_manager.py` (502 lines)
- **Purpose**: SQLite-backed persistence layer for options positions. Stores open/closed/expired positions in `engine/db/options_positions.db`. Provides `add_position`, `get_positions`, `close_position`, `update_greeks`, `check_roll_candidates`, `get_expiring_soon`, and `get_portfolio_greeks`. Delegates Greeks monitoring to the embedded `GreeksMonitor` instance.
- **Import status**: CLEAN — imports resolve
  - `from .greeks_monitor import GreeksMonitor, PortfolioGreeks`
  - `from .strategy_executor import OptionsLeg, OptionsOrder`
  - Stdlib: `json`, `sqlite3`, `uuid`, `pathlib`, `contextlib`, `dataclasses`, `datetime`
- **yfinance**: ABSENT
- **Wired in main.py**: YES (indirectly via `options_router.py`)
- **Notes**: File is 502 lines — exceeds the 400-line guideline. Could be split into `_persistence.py` (SQLite helpers) + `position_manager.py` (manager class). DB path resolves to `engine/db/options_positions.db`; the `db/` directory is created automatically on first use.

---

### 5. `engine/options/premium_calculator.py` (299 lines)
- **Purpose**: Black-Scholes pricing (`black_scholes_price`), probability of profit (`probability_of_profit`), expected value (`expected_value`), credit spread metrics (`get_credit_spread_metrics`), and P&L at expiry scenarios (`pnl_at_expiry`). Also defines `PremiumScanResult` dataclass.
- **Import status**: CLEAN — stdlib only (`math`, `logging`, `dataclasses`, `datetime`, `typing`)
- **yfinance**: ABSENT
- **Wired in main.py**: YES (indirectly via `options_router.py` — strategy builder functions call premium_calculator implicitly through Greeks)
- **Notes**: Cleanest file in the module. Under the 400-line guideline. Note: `_norm_cdf` and `_norm_pdf` are duplicated from `greeks_monitor.py` — minor code smell but deliberately isolated to avoid circular imports.

---

### 6. `engine/options/strategy_executor.py` (662 lines)
- **Purpose**: Defines `OptionsStrategy`, `VIXRegime`, `RegimeState` enums; `OptionsLeg` and `OptionsOrder` dataclasses; seven strategy builder functions (`build_covered_call`, `build_bull_put_spread`, `build_bear_call_spread`, `build_iron_condor`, `build_protective_put`, `build_straddle`, `build_strangle`); VIX regime classifier (`classify_vix_regime`); and full order validation engine (`validate_order`) with regime-aware blocking rules.
- **Import status**: CLEAN — stdlib only at module level (`logging`, `dataclasses`, `datetime`, `enum`, `typing`)
- **yfinance**: ABSENT
- **Wired in main.py**: YES (indirectly via `options_router.py`)
- **Notes**: At 662 lines this is **approaching the 800-line hard limit**. The `VIXRegime` enum here uses a simplified 4-tier scale (LOW/NORMAL/HIGH/EXTREME) which **conflicts** with the canonical 6-tier VIX scale (VERY_LOW/LOW/NORMAL/ELEVATED/HIGH/EXTREME) defined in the broader JARVIS system. This is a known inconsistency to reconcile.

---

### 7. `engine/routers/options_router.py` (427 lines)
- **Purpose**: FastAPI router exposing 6 REST endpoints:
  - `GET /chain/{symbol}` — live options chain
  - `GET /greeks` — portfolio-level aggregated Greeks
  - `GET /iv-rank/{symbol}` — IV Rank calculation
  - `POST /strategy/recommend` — VIX regime-aware strategy recommendation
  - `GET /positions` — options positions (filterable by status)
  - `GET /module/status` — OptionsMarketModule health from MultiMarketOrchestrator
- **Import status**: CLEAN — router imports successfully; all lazy imports within endpoint handlers resolve correctly
- **yfinance**: ABSENT
- **Wired in main.py**: **NO — CRITICAL GAP**
  - The router is **never imported or registered** in `main.py`
  - `main.py` imports 13 other routers explicitly but `options_router` is missing
  - All 6 endpoints are inaccessible at runtime

---

## Import Dependency Graph

```
options_router.py
  ├── options.chain_fetcher       (imports greeks_monitor internally)
  ├── options.position_manager    (imports greeks_monitor + strategy_executor)
  ├── options.strategy_executor   (stdlib only)
  ├── data.market_data            (MarketDataManager — confirmed OK)
  └── orchestrator                (get_orchestrator — confirmed OK)

options.chain_fetcher
  ├── options.greeks_monitor      (iv_rank, calculate_greeks)
  └── backtest.data_loader        (BacktestDataLoader — confirmed OK)

options.greeks_monitor
  └── options.premium_calculator  (black_scholes_price — lazy import)

options.position_manager
  ├── options.greeks_monitor
  └── options.strategy_executor
```

---

## Compile-Check Results

All 5 core options modules imported cleanly from `.venv/Scripts/python`:

| Module | Import Status | Key Symbol |
|--------|--------------|-----------|
| `options.chain_fetcher` | OK | `OptionChainFetcher` (dataclass) |
| `options.greeks_monitor` | OK | `GreeksMonitor` (class) |
| `options.position_manager` | OK | `OptionsPositionManager` (class) |
| `options.premium_calculator` | OK | `black_scholes_price` (function) |
| `options.strategy_executor` | OK | `OptionsStrategy` (enum) |
| `routers.options_router` | OK | `router` (APIRouter, 6 routes) |

Dependent modules also confirmed clean:
- `data.market_data.MarketDataManager` — OK
- `backtest.data_loader.BacktestDataLoader` — OK
- `orchestrator.get_orchestrator` — OK

---

## yfinance Status

**Zero yfinance references across all 6 options files and the router.**
The module was fully migrated to `MarketDataManager`/`BacktestDataLoader`.

---

## Overall Assessment

### What Works
- All 6 options modules import cleanly with zero errors
- No yfinance dependencies remain
- Black-Scholes Greeks, IV solver, and premium calculator are correct and self-contained
- Strategy builders produce valid `OptionsOrder` objects for all 7 supported strategies
- Regime validation logic in `strategy_executor.validate_order` is sound
- `OptionsPositionManager` SQLite persistence is solid with proper WAL mode and rollback
- `GreeksMonitor` delta/gamma alerting logic is correct

### What Is Broken or Missing

1. **CRITICAL: Router not wired into main.py**
   - `options_router.py` exists and works but is never registered with the FastAPI app
   - All 6 endpoints return 404 in the running engine
   - Fix: Add import + `app.include_router` in `main.py` (3 lines)

2. **SIGNIFICANT: Chain data returns empty calls/puts**
   - `fetch_chain()` builds the chain scaffold (symbol, expiry, IVR, underlying price) but returns zero contracts
   - A true Polygon options chain endpoint integration is needed to populate strikes
   - This means `/options/chain/{symbol}` will return a 404 ("Empty options chain")

3. **MINOR: VIX regime inconsistency**
   - `strategy_executor.py` uses a 4-tier VIX scale (LOW/NORMAL/HIGH/EXTREME)
   - The canonical JARVIS system uses a 6-tier scale (VERY_LOW/LOW/NORMAL/ELEVATED/HIGH/EXTREME)
   - The `options_router` strategy recommendations use the 4-tier mapping only

4. **MINOR: File size guideline violations**
   - `strategy_executor.py`: 662 lines (approaching 800-line hard limit)
   - `position_manager.py`: 502 lines (exceeds 400-line typical guideline)
   - `chain_fetcher.py`: 484 lines (exceeds 400-line typical guideline)
   - `greeks_monitor.py`: 466 lines (exceeds 400-line typical guideline)

5. **MINOR: IV Rank is a proxy, not true IVR**
   - Uses historical realized volatility (close-to-close HV21) as a substitute for ATM IV term structure
   - Acceptable for paper trading but should be replaced with actual IV snapshots before live trading

---

## Recommended Next Steps

### Priority 1 (Blocking — do immediately)

**Wire the options router into main.py:**

In `engine/main.py`, add to the import block (near line 94, after schwab_router):
```python
from routers.options_router import router as options_router
```

Add to the `include_router` block (near line 868):
```python
app.include_router(options_router, prefix="/options", tags=["options"])
```

This single change activates all 6 endpoints at `/options/chain/{symbol}`, `/options/greeks`, `/options/iv-rank/{symbol}`, `/options/strategy/recommend`, `/options/positions`, and `/options/module/status`.

### Priority 2 (Near-term)

**Integrate real options chain data:**
- Connect `chain_fetcher.fetch_chain()` to Polygon.io options chain endpoint (`/v3/snapshot/options/{underlyingAsset}`)
- Populate `calls` and `puts` lists with actual strike data
- This is the main capability gap — without it, the chain endpoint is non-functional

**Align VIX regime tiers:**
- Update `strategy_executor.VIXRegime` to match the canonical 6-tier scale or add a mapping layer
- Alternatively, import the existing 6-tier `RegimeClassifier` from `backtest/regime.py`

### Priority 3 (Code quality)

**Split oversized files:**
- `strategy_executor.py` (662 lines): Split `validate_order` + regime logic into `strategy_validator.py`
- `position_manager.py` (502 lines): Split SQLite helpers into `_db.py`, keep manager class in `position_manager.py`

**True IV Rank implementation:**
- Store daily ATM IV snapshots in the positions DB
- Compute IVR from actual IV time series rather than HV proxy
- Required for accurate strategy selection before live trading

---

*Report generated by Agent-8 | Audit complete*
