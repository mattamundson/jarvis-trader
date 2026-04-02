# Experimental Learning Modules — Phase 2 Candidates

This directory contains learning system modules that are **not yet integrated into the core trading pipeline**. They are exploratory features available for analysis and testing.

## Modules

### pattern_extractor.py (~230 lines)
Automatic extraction of recurring trading patterns from historical trades.

**Features:**
- Time-of-day pattern detection (win rates by hour)
- Regime-based pattern discovery (TRENDING vs. CHOPPY)
- Win/loss streak pattern analysis

**Status:** Functional but not validated against live trading.

### session_memory.py (~170 lines)
Multi-day lesson persistence and market condition tagging.

**Features:**
- JSON-backed lesson storage
- Lesson filtering by market condition (TRENDING, CHOPPY, etc.)
- Session-level outcome classification

**Status:** Functional, useful for manual review.

### strategy_tuner.py (~210 lines)
Conservative parameter adjustment suggestions based on recent trade performance.

**Features:**
- Win-rate analysis
- Conservative bounds on suggested changes (max 15% delta)
- Safety parameter exclusion (never suggests tuning risk controls)

**Status:** Functional but recommendations require human validation.

### trade_classifier.py (~250 lines)
Single-trade outcome quality grading (A–F).

**Features:**
- R-multiple calculation
- Setup and execution quality scoring
- Factor-based grade explanation

**Status:** Functional as analysis tool.

## Integration Requirements for Phase 3

Before promoting any module to production:

1. **Backtesting Validation**: All 4 modules must show Sharpe >= 1.5, Profit Factor >= 2.0 across MCL (1h) and MNQ (1h)
2. **Safety Lock-Down**: Confirm no automatic tuning of:
   - `MAX_POSITION_SIZE_PCT`
   - `MAX_DAILY_LOSS_PCT`
   - `EMERGENCY_DRAWDOWN_HALT_PCT`
   - `MARGIN_UTIL_MAX`
   - Kill switch parameters
3. **Human Approval Workflow**: All suggestions routed through FundManagerAgent for explicit approval
4. **Test Coverage**: Expand `test_learning.py` to cover edge cases and failure modes

## Current Usage

Available via API endpoints:
- `GET /learning/patterns` — Extract patterns from closed trades
- `GET /learning/classify?trade_id=...` — Grade a single trade
- `GET /learning/suggestions` — Get parameter adjustment ideas
- `GET /learning/memory` — Retrieve recorded lessons
- `POST /learning/memory` — Record a new lesson

These endpoints are optional and do not block trading operations.

## Notes

- No router endpoints call these modules outside of `learning_router.py`
- Test coverage in `engine/tests/test_learning.py`
- Kept in codebase (not deleted) to preserve ~650 lines of design work
