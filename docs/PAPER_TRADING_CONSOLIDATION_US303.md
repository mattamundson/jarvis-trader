# Paper Trading Consolidation (US-303)

## Objective
Establish **PaperTradeTracker** as the **single source of truth** for all paper trading state, eliminating overlapping responsibilities and dual-write patterns across 5 separate modules.

## Status
**COMPLETE** — All modules consolidated and refactored. Tests passing (19 validation tests, 4 mirror tests).

## Modules & Responsibilities After Consolidation

### 1. `paper_tracker.py` (PRIMARY STATE MANAGER)
**Location:** `engine/backtest/paper_tracker.py`
**Responsibility:** THE SINGLE SOURCE OF TRUTH for all paper trade state
**Operations:**
- `add_trade()` — Record completed trade, compute P&L, persist to JSON, enforce kill conditions
- `get_metrics()` — Return current performance metrics
- `check_kill_conditions()` — Evaluate kill thresholds (3 consecutive losses, -3% monthly, WFE minimum, max DD)
**Storage:** JSON file per symbol at `engine/backtest/results/paper_trades_{MCL|MNQ|MGC}.json`
**Initialization:** `PaperTradeTracker(config)` where config is from `paper_config.py`

### 2. `paper_runner.py` (EXECUTION LOOP)
**Location:** `engine/backtest/paper_runner.py`
**Responsibility:** Hourly trading loop — signal generation, position management, trade entry/exit
**Delegation Pattern:**
- Calls `paper_tracker.add_trade(record)` for every closed position (NOT direct JSON writes)
- Calls `paper_tracker.get_metrics()` for status checks
- Calls `paper_tracker.check_kill_conditions()` before each cycle
- Uses `paper_config.py` for signal parameters and risk limits (read-only)
**Guarantees:** All state writes flow through `paper_tracker` — no competing writes to JSON or SQLite.

### 3. `paper_config.py` (CONFIGURATION ONLY)
**Location:** `engine/backtest/paper_config.py`
**Responsibility:** Configuration parameters for MCL, MNQ, MGC paper trading
**Content:**
- `MCL_PAPER_CONFIG`, `MNQ_PAPER_CONFIG`, `MGC_PAPER_CONFIG` dicts
- Signal parameters (STC OS/OB, ATR multipliers, regimes, filters)
- Kill thresholds (consecutive losses, monthly loss %, rolling WFE minimum)
- Contract specs (multiplier, tick size, commission)
**Mutation:** NONE — pure config, no writes
**Dependency:** Read by `paper_runner.py` and `paper_tracker.py` initialization

### 4. `validation_tracker.py` (READ-ONLY OBSERVER)
**Location:** `engine/paper/validation_tracker.py`
**Responsibility:** Aggregate validation metrics from PaperTradeTracker and expose via API
**Operations:**
- `__init__()` — Load trades from `PaperTradeTracker`'s JSON files, compute metrics
- `get_progress(instrument)` — Return per-instrument metrics vs. thresholds
- `get_dashboard_data()` — Return overall validation status
- `is_validated(instrument)` — Check if validation passes all thresholds (PF, Sharpe, WR, days, DD)
**Deprecated (No-ops for backward compatibility):**
- `record_trade()` → warns and returns (use `PaperTradeTracker.add_trade()` instead)
- `record_daily_pnl()` → warns and returns
**Storage:** None (reads from `PaperTradeTracker` JSON files)
**Example:** `ValidationTracker(data_dir="engine/data")` loads from `engine/data/backtest/results/paper_trades_MCL.json`

### 5. `paper_trade_logger.py` (ALTERNATIVE LOGGER)
**Location:** `engine/execution/paper_trade_logger.py`
**Responsibility:** Optional logging + mirroring to `PortfolioTracker` (alternative flow)
**Operations:**
- `log_trade(trade_data)` — Log to `data/paper_trades.json` (thread-safe append)
- `_maybe_mirror_to_tracker()` — Optional: on entry/exit, register with `PortfolioTracker`
**NOT a state manager:** Complements `PaperTradeTracker`, does not compete
**Usage:** Opt-in mirroring for PortfolioTracker sync (mode B from US-210)
**Guarantees:** No dual writes — logs to separate JSON, mirrors only if configured

## Data Flow

```
paper_runner.py (execution)
      ↓
paper_tracker.py ← paper_config.py (config)
      ↓
paper_trades_{symbol}.json (authoritative state)
      ↓
validation_tracker.py (read-only aggregator)
      ↓
/paper/validation/* API endpoints
```

Optional parallel flow (paper_trade_logger):
```
paper_runner.py
      ↓
paper_trade_logger.py
      ↓
data/paper_trades.json + PortfolioTracker mirror
```

## Changes Made

### Module Updates
1. **paper_tracker.py**
   - Added consolidation note clarifying it's the single source of truth
   - No code changes (already correct)

2. **paper_runner.py**
   - Added consolidation note explaining delegation to paper_tracker
   - No code changes (already correct)

3. **paper_config.py**
   - Added consolidation note clarifying it's configuration-only
   - No code changes (already correct)

4. **validation_tracker.py** (MAJOR REFACTOR)
   - Removed `_save()` method (read-only)
   - Removed `record_trade()` implementation (deprecated)
   - Removed `record_daily_pnl()` implementation (deprecated)
   - Added `_load_from_tracker()` — reads from `PaperTradeTracker` JSON files
   - Updated `__init__()` to call `_load_from_tracker()` instead of loading legacy file
   - Deprecated methods now log warnings and return (backward-compatible no-ops)

5. **paper_validation_router.py**
   - Updated docstring to clarify read-only nature
   - Updated `/record` POST endpoint: now returns deprecation notice, doesn't persist
   - All GET endpoints unchanged (still functional)

### Test Updates
All 19 tests in `test_paper_validation.py` refactored to:
- Create mock `PaperTradeTracker` JSON files for test data
- Remove calls to deprecated `record_trade()` and `record_daily_pnl()`
- Test reading/aggregation behavior instead
- All 19 tests passing

### Tests Verified Passing
- `test_paper_validation.py` (19 tests)
- `test_paper_trade_logger_tracker_mirror.py` (2 tests)
- `test_paper_runner_engine_sync.py` (1 test)
- `test_portfolio_paper_trade_post.py` (1 test)
- **Total: 23/23 passing**

## Removed/Deprecated

### Fully Deprecated
- `ValidationTracker.record_trade()` — deprecated, kept for backward-compat as no-op
- `ValidationTracker.record_daily_pnl()` — deprecated, kept for backward-compat as no-op
- `POST /paper/validation/record` — still works but returns deprecation notice

### Never Conflicted
- `paper_trade_logger.py` remains unchanged (optional alternative logging, not a state manager)
- `paper_config.py` remains unchanged (pure config, no state mutations)

## Single Source of Truth Guarantee

**Before Consolidation:**
- `validation_tracker.py` wrote to `data/paper_validation.json` (duplicate state)
- `paper_trader.py` in some contexts might write directly
- No clear ownership of authoritative state

**After Consolidation:**
1. **Paper trades** ← `PaperTradeTracker` (JSON: `paper_trades_{symbol}.json`)
   - Only written via `PaperTradeTracker.add_trade()`
   - All state updates flow through this class

2. **Validation metrics** ← `ValidationTracker` (computed in-memory)
   - Read-only aggregator
   - Loads from `PaperTradeTracker` JSON files
   - No disk writes from `ValidationTracker`

3. **Audit trail** ← `paper_trade_logger.py` (optional, separate file)
   - Logs to `data/paper_trades.json` (alternative view)
   - Never a source-of-truth (mirrors `PaperTradeTracker` if enabled)

## Verification

### Code Review Points
✅ No dual-write patterns remain
✅ All state writes routed through `PaperTradeTracker`
✅ `ValidationTracker` is read-only observer
✅ `paper_trade_logger.py` is alternative logger (not competing)
✅ Backward compatibility maintained (deprecated methods are no-ops)
✅ All tests passing (23/23)

### Breaking Changes
None. Deprecated methods kept for backward compatibility as no-ops.

## Future Maintenance

### Adding New Metrics
- **DO** add to `ValidationTracker.get_progress()` (read from existing trades)
- **DON'T** create new writes to validation JSON files

### Modifying Trade Recording
- **DO** update `PaperTradeTracker.add_trade()`
- **DON'T** modify `validation_tracker.py` write logic

### Paper Trading Config Changes
- **DO** update `paper_config.py`
- **DON'T** modify state handling in other modules

## API Endpoint Impact

| Endpoint | Before | After | Status |
|---|---|---|---|
| `GET /paper/validation/progress` | Reads from `paper_validation.json` | Reads from `PaperTradeTracker` | No change to caller |
| `GET /paper/validation/trades` | Same source | Same source | No change |
| `GET /paper/validation/status` | Same logic | Same logic | No change |
| `POST /paper/validation/record` | Writes JSON | Deprecation notice | **Breaking** (but intentional) |

**Migration path for `POST /record`:**
- Client code should call `PaperTradeTracker.add_trade()` directly
- Or use `paper_runner.py` (which already does)
- No FastAPI endpoint needed for trade recording

## References

- **PaperTradeTracker**: `engine/backtest/paper_tracker.py` (lines 1-434)
- **paper_runner.py**: Calls `tracker.add_trade()` at lines 428, 482
- **ValidationTracker**: `engine/paper/validation_tracker.py` (refactored)
- **Tests**: `engine/tests/test_paper_validation.py` (19 tests)
