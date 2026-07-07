# JARVIS TRADER — Phase 3 Backlog

> Strategic technical debt items and Phase 3 feature blockers
> Last updated: 2026-04-02
> Total items: 7

## Schwab Connector Completion

**Status**: Implementation in progress, NOT ready for production
**Owner**: Matt (trader) + DevOps
**Priority**: HIGH (blocks equities/options support)
**Dependency**: OAuth2 sandbox validation, token refresh automation
**Story**: *Future* — Equities & Options Support Phase

### Description
The Schwab connector (engine/execution/schwab_connector.py) has partial implementation but is guarded by `check_schwab_ready()` which blocks all usage until completion. Single-leg options orders are implemented but untested.

### Acceptance Criteria (Phase 3)
- [ ] Full OAuth2 flow integration with dashboard (currently requires manual 7-day token refresh)
- [ ] Automated token refresh (eliminate manual refresh requirement)
- [ ] Integration with order router dispatch (route equities/options through Schwab)
- [ ] Testing against live Schwab sandbox
- [ ] Error handling refinements (handle rate limits, invalid symbols, margin violations)
- [ ] Logging and observability improvements
- [ ] Remove `check_schwab_ready()` guard once complete and tested
- [ ] Dashboard component to manage Schwab credentials and view connection status

### Current Implementation
- Quote fetching: working
- Options chain retrieval: working
- Single-leg options order: implemented but untested
- Order cancellation: implemented but untested

### Blockers
- OAuth2 flow requires interactive user approval (not automated yet)
- Manual token refresh every 7 days (requires external script or dashboard action)
- No integration with order router (orders currently route only to IB Gateway)

### Estimated Effort
- OAuth2 automation: 3-4 days (dashboard + backend token manager)
- Sandbox testing: 2-3 days
- Integration: 2-3 days
- Total: 1-2 weeks

---

## IB Gateway Disconnect Cleanup

**Status**: TODO at engine/execution/ib_gateway_connector.py ~line 257
**Owner**: Matt (trader)
**Priority**: LOW (deferred to live trading phase)
**Dependency**: Phase 3 (live trading enabled)
**Story**: *Future* — Live Trading Phase

### Description
When live trading is enabled (LIVE_TRADING_ENABLED = True, Phase 3), the disconnect() method must call `self._ib_client.disconnect()` to cleanly close the IB Gateway connection. Currently it's stubbed with `pass`.

### Implementation
```python
# Current (Phase 2):
if self._ib_client:
    try:
        # TODO: When live trading implemented, call self._ib_client.disconnect()
        pass
    except Exception as exc:
        logger.error("Error disconnecting from IB Gateway: %s", exc)

# Phase 3:
if self._ib_client:
    try:
        self._ib_client.disconnect()
        logger.info("IB Gateway disconnected cleanly")
    except Exception as exc:
        logger.error("Error disconnecting from IB Gateway: %s", exc)
```

### Why Deferred
- Only relevant when live trading is enabled (Phase 3)
- Paper trading mode (Phase 2) keeps IB Gateway connected for the entire session
- No safety risk in Phase 2 (connection is meant to stay open)

### Estimated Effort
- Implementation: 30 minutes
- Testing: 1 hour
- Total: 1.5 hours

---

## RL Agent Validation Gate Enhancement

**Status**: Recommendation documented at engine/strategies/rl_agent.py ~line 173
**Owner**: Matt (trader) + ML engineer
**Priority**: MEDIUM (performance gate refinement)
**Dependency**: Sufficient out-of-sample (OOS) data (30+ days live validation)
**Story**: *Future* — RL Trading Mode Phase

### Description
The RL agent validation gates check `hold_rate` (blended metric) but should also validate `flat_hold_rate` (hold rate when the agent has NO open position) as a stronger overtrading guard. This requires 30+ days of OOS data to calibrate thresholds.

### Recommendation
Add a new validation gate once sufficient OOS data is collected:

```python
# Phase 3 addition to VALIDATION_GATES in rl_config.py:
"min_flat_hold_rate": 0.50

# Phase 3 addition to validation logic in rl_agent.py:
averaged["passes_flat_hold_gate"] = averaged["flat_hold_rate"] >= 0.50
```

### Why Phase 3
- Requires 30+ days of live OOS validation data
- Flat hold rate metric only meaningful after sufficient trading history
- Current hold_rate gate is sufficient for Phase 2

### Rationale
- `hold_rate` = overall decision quality (includes when agent already has position)
- `flat_hold_rate` = decision quality when agent has NO position (purer signal)
- Flat hold rate >= 0.50 is more restrictive than overall hold rate, catches overtrading

### Estimated Effort
- Data analysis: 2-3 days (after 30-day validation period)
- Gate implementation: 1-2 hours
- Testing: 2-3 hours
- Total: 3-5 days (dependent on validation data)

---

## Database Migration: Paper Trades Insert/Close

**Status**: Test placeholders at engine/tests/test_integration.py (uncommented notes)
**Owner**: Matt (trader) + DBA
**Priority**: MEDIUM (data persistence for Phase 3)
**Dependency**: DatabaseManager enhancement
**Story**: *Future* — Data Persistence Phase

### Description
The test suite has placeholders for DatabaseManager methods that don't exist yet:
- `insert_paper_trade()` — create DB record when trade opens
- `close_paper_trade()` — update DB record when trade closes

Currently, paper trade tracking is in-memory only (PaperTradeTracker).

### Implementation (Phase 3)
1. Add `insert_paper_trade(symbol, side, quantity, entry_price, ...)` to DatabaseManager
2. Add `close_paper_trade(trade_id, exit_price, exit_time, pnl, ...)` to DatabaseManager
3. Update PaperTradeTracker to call these methods
4. Uncomment assertions in test_integration.py once methods exist
5. Add persistence tests

### Why Phase 3
- Phase 2 validation can work with in-memory tracking
- Phase 3 requires persistent historical record for learning system
- Learning system (engine/learning/) needs historical trades to generate patterns

### Current Test Placeholders
```python
# engine/tests/test_integration.py
# NOTE (Phase 3 TODO): Uncomment once DatabaseManager gains insert_paper_trade()
# NOTE (Phase 3 TODO): Uncomment once DatabaseManager gains close_paper_trade()
```

### Estimated Effort
- DatabaseManager methods: 2-3 hours
- PaperTradeTracker integration: 1-2 hours
- Testing: 2-3 hours
- Total: 5-8 hours

---

## IB Gateway Reconnection Logic (Sprint 11)

**Status**: NEW feature (not in Phase 2)
**Owner**: Matt (trader)
**Priority**: HIGH (reliability blocker for 30-day validation)
**Dependency**: None
**Story**: US-1101 (Sprint 11)

### Description
ib_gateway_connector.py has connection management but NO auto-reconnect logic. If IB Gateway drops during trading, the engine silently propagates the error instead of attempting recovery.

### Requirements (Sprint 11)
- Exponential backoff: 3 retries at 2s, 4s, 8s intervals
- Connection state: connected, disconnecting, reconnecting, failed
- Heartbeat check every 60 seconds
- On persistent failure, log CRITICAL and emit safety event
- SafetyLayer integration
- Unit tests in engine/tests/test_ib_reconnect.py

### Estimated Effort
- Implementation: 3-4 hours
- Testing: 2-3 hours
- Total: 5-7 hours

### Risk Mitigation
- Auto-reconnect prevents false kill-switch triggers during transient network issues
- Critical for 30-day paper validation (currently: one brief disconnect = trading halt)

---

## Automated Database Backup (Sprint 11)

**Status**: NEW feature (not in Phase 2)
**Owner**: Matt (trader) + DevOps
**Priority**: HIGH (data loss prevention during 30-day validation)
**Dependency**: APScheduler (already vendored)
**Story**: US-1102 (Sprint 11)

### Description
paper_trades.db has 98 trades and growing. Zero automated backup exists. One hardware failure or corruption = 30-day validation data loss.

### Requirements (Sprint 11)
- New file: engine/backup/db_backup.py (< 150 lines)
- SQLite backup API (crash-safe, not file copy)
- Backup to data/backups/ with timestamps
- Retention: 30 daily backups, auto-delete older
- Scheduled nightly at 23:30 UTC via APScheduler
- GET /system/backup-status endpoint
- Async (never blocks event loop)

### Estimated Effort
- Implementation: 2-3 hours
- Testing: 1-2 hours
- Total: 3-5 hours

### Risk Mitigation
- Nightly backups ensure max 24-hour data loss if corruption occurs
- Retention policy prevents unlimited growth
- Async design keeps trading latency unaffected

---

## OpenAPI Documentation (Sprint 11)

**Status**: NEW feature (not in Phase 2)
**Owner**: Engineering
**Priority**: MEDIUM (developer experience)
**Dependency**: None
**Story**: US-1103 (Sprint 11)

### Description
143+ endpoints exist but most lack clear descriptions in Swagger. Focus on top 30 most-used endpoints.

### Requirements (Sprint 11)
- At least 30 endpoints get `description=` and `response_model=`
- Priority: /analytics/*, /health/*, /risk/*, /paper/*, /validation/*
- 1-2 sentence descriptions
- Consistent tags
- Clean Swagger rendering at /docs

### Estimated Effort
- Audit + prioritization: 1-2 hours
- Endpoint documentation: 3-4 hours
- Testing in Swagger: 1 hour
- Total: 5-7 hours

---

## Dashboard Build Verification (Sprint 11)

**Status**: NEW feature (not in Phase 2)
**Owner**: Engineering
**Priority**: MEDIUM (CI/CD hygiene)
**Dependency**: None
**Story**: US-1104 (Sprint 11)

### Description
Dashboard build is currently healthy but needs verification script and TypeScript type definitions for new endpoints added in Sprints 8-11.

### Requirements (Sprint 11)
- Script: scripts/verify_dashboard_build.sh (runs build check)
- Add type definitions in dashboard/lib/api.ts for:
  - /analytics/performance
  - /analytics/trades/by-*
  - /pipeline/profiling/*
  - /validation/alerts
- Capture route count and warnings
- Exit code 0 on success, 1 on failure

### Estimated Effort
- Type definitions: 1-2 hours
- Verification script: 1 hour
- Testing: 1 hour
- Total: 3-4 hours

---

## Summary Table

| Item | Owner | Priority | Phase | Effort | Blocker |
|------|-------|----------|-------|--------|---------|
| Schwab Completion | Matt + DevOps | HIGH | 3 | 1-2w | Equities support |
| IB Disconnect Cleanup | Matt | LOW | 3 | 1.5h | Live trading only |
| RL Validation Gate | Matt + ML | MEDIUM | 3 | 3-5d | Post-validation data |
| DB Paper Trade Persistence | Matt + DBA | MEDIUM | 3 | 5-8h | Learning system |
| IB Reconnection (US-1101) | Matt | HIGH | 11 | 5-7h | 30-day validation |
| DB Backup Automation (US-1102) | Matt + DevOps | HIGH | 11 | 3-5h | Data loss prevention |
| OpenAPI Docs (US-1103) | Engineering | MEDIUM | 11 | 5-7h | Developer UX |
| Dashboard Build (US-1104) | Engineering | MEDIUM | 11 | 3-4h | CI/CD hygiene |

**Total Effort**: ~2-3 weeks (Phase 3 items) + ~1 week (Sprint 11 items)

---

## Dependencies & Ordering

**Sprint 11 (hard deadline before 30-day validation)**:
1. IB Reconnection (US-1101) — blocks reliability
2. DB Backup (US-1102) — blocks data safety
3. OpenAPI Docs (US-1103) — documentation debt
4. Dashboard Build (US-1104) — CI/CD debt

**Phase 3 (post-validation)**:
1. Schwab Completion — unlocks equities/options
2. Database Migrations — supports learning system
3. RL Validation Enhancement — improves agent quality
4. IB Disconnect Cleanup — live trading hygiene
