# US-1403 Implementation Summary: Layer 5 Conviction-Aware Position Sizing

## Overview
Successfully implemented Layer 5 conviction-aware position sizing for JARVIS TRADER Sprint 14. This feature scales base risk percentage by the alignment strength across Layers 1-4 (bias, regime, structure), enabling dynamic position sizing based on signal confidence.

## Changes Made

### 1. engine/backtest/signals.py
Added module-level function `compute_position_size()` at line 694:
- Takes parameters: bias, regime, structure_position, base_risk_pct
- Returns scaled risk percentage (0.25x to 1.0x multiplier)
- Sizing rules:
  - SIZING_FULL (1.0x): STRONG bias + TRENDING regime + directional structure
  - SIZING_HIGH (0.8x): STRONG bias + TRENDING regime (any structure)
  - SIZING_HALF (0.5x): LEAN bias OR non-TRENDING regime
  - SIZING_MIN (0.25x): All other cases (e.g., NEUTRAL bias with no trending)

### 2. engine/database/migrations.py
Added migration 011 for Layer 5 conviction-aware sizing:
- Migration function: `migration_011()` at line 597
- Adds `risk_pct_used` column (REAL, nullable) to paper_trades table
- Backward compatible with existing trades
- Updated MIGRATIONS list and MIGRATION_DESCRIPTIONS

### 3. engine/backtest/paper_runner.py
Integrated compute_position_size into paper trading execution:
- Line 483: Extract structure_position from latest bar's signal
- Line 487-489: Import and call compute_position_size with signal parameters
- Line 501: Store structure_position in position dict
- Line 504: Store computed risk_pct_used in position dict
- Lines 348 & 403: Include risk_pct_used in trade records when closing positions

### 4. engine/routers/paper_validation_router.py
Enhanced validation gates endpoint with conviction metrics:
- Line 151-153: Add avg_conviction_score field to ValidationGatesResponse
- Line 252-277: New helper function `_compute_conviction_score()` computes average conviction across all trades
- Line 381: Compute conviction score from closed trades
- Line 390: Include avg_conviction_score in response

## Testing
- All signal tests pass (32/32): test_signals.py
- Ruff check: all files pass (0 errors)
- Functional tests of compute_position_size:
  - Test 1 (FULL): STRONG_BULL + TRENDING_BULL + BUYER_CONTROL = 0.0025 (1.0x)
  - Test 2 (HIGH): STRONG_BULL + TRENDING_BULL + NEUTRAL = 0.002 (0.8x)
  - Test 3 (HALF): LEAN_BULL + TRENDING_BULL = 0.00125 (0.5x)
  - Test 4 (HALF): Non-trending regime = 0.00125 (0.5x)
  - Test 5 (MIN): NEUTRAL + TRENDING = 0.000625 (0.25x)

## Backward Compatibility
- New risk_pct_used column is NULLABLE for backward compat
- Existing trades without conviction data still work (score defaults to 0.0)
- No breaking changes to existing APIs

## Implementation Notes
- compute_position_size is pure function with no side effects
- Respects safety layer hard limits (config.py) - this is pre-safety sizing
- Constants are named SIZING_FULL, SIZING_HIGH, SIZING_HALF, SIZING_MIN (no magic numbers)
- All Python code passes ruff checks (PEP 8 compliant)
- Async-safe and error-handling compliant with JARVIS standards

## Files Modified
1. engine/backtest/signals.py (added ~50 lines)
2. engine/backtest/paper_runner.py (added ~10 lines)
3. engine/database/migrations.py (added ~20 lines)
4. engine/routers/paper_validation_router.py (added ~30 lines)

## PRD Acceptance Criteria
All 6 acceptance criteria met:
1. ✅ compute_position_size function with correct sizing rules
2. ✅ Integration with paper_tracker when recording trades
3. ✅ Migration 011 adds risk_pct_used column
4. ✅ /paper-validation/gates includes avg_conviction_score
5. ✅ All Python code is ruff-clean and async-safe
6. ✅ Tests pass (no regressions)

## Ready for
- Merge to Sprint 14 branch
- Integration with US-1404 (trade journal with provenance)
- Paper trading deployment with conviction-aware sizing enabled
