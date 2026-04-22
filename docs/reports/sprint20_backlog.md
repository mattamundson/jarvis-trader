# Sprint 20 Backlog — Deferred from Sprint 19

## Deferred Bugs (Medium Priority)

### B3: ValidationTracker reads stale JSON files
- **File**: engine/paper/validation_tracker.py
- **Root cause**: Reads from data/backtest/results/paper_trades_{MCL,MNQ}.json on init, never refreshes. Completely separate from SQLite/JSONL trade store.
- **Impact**: /paper/validation/status and /paper/validation/trades return 0 trades instead of actual count
- **Fix needed**: Either refresh on each request, or replace with direct SQLite query

### B4: ValidationTracker empty trade list
- **File**: engine/paper/validation_tracker.py
- **Root cause**: Same as B3 — JSON files are empty/stale, so get_all_trades() returns []
- **Impact**: Validation progress shows 0 trades for MCL/MNQ
- **Fix needed**: Read from paper_trades SQLite table directly

### B9: SQLite vs in-memory PnL divergence
- **Files**: engine/portfolio/tracker.py, engine/routers/portfolio_router.py
- **Root cause**: get_performance() reads in-memory _closed list; paper-phase-summary reads via get_trade_history() which queries SQLite. DB write failures (silently caught) cause divergence.
- **Impact**: Different endpoints report different PnL totals ($30 vs $130 observed in Sprint 18)
- **Fix needed**: Single source of truth — either always read from SQLite, or ensure writes are transactional

## Notes
- B5 (profit_factor=9999.0): This is intentional — 9999.0 is the sentinel for infinity (float('inf') not JSON-serializable). Acceptable behavior.
- B3/B4/B9 require architectural changes beyond Sprint 19 scope.
