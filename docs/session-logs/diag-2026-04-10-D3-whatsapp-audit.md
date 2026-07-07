# WhatsApp Alert Audit — 28 BUY Decisions Unalerted on Apr 7–8

## Status Update — 2026-04-11

This note is now partially superseded by the current implementation.

- Cooldown logic has been extracted into `engine/notifications/pipeline_alert_cooldown.py`
- Runtime uses `settings.ALERT_COOLDOWN_MINUTES` instead of a hardcoded
  `ALERT_COOLDOWN_HOURS`
- Suppressed cooldown events are persisted to `alert_log` via
  `_log_pipeline_whatsapp_to_alert_log(...)`
- Regression coverage exists in `engine/tests/test_pipeline_alert_cooldown.py`
  and currently passes

Treat the findings below as the historical root-cause analysis from 2026-04-10,
not as a description of the current code.

## Root Cause: 2-Hour Cooldown Rate Limit

**The Problem:**
28 BUY decisions on Apr 7 + 28 BUY decisions on Apr 8 generated in the `decisions` table but **zero WhatsApp alerts** reached the user. Expected: alerts for every non-HOLD signal.

**Root Cause (Confirmed):**
- **Line 218 (`engine/main.py`)**: `ALERT_COOLDOWN_HOURS = 2` (not configurable via .env)
- **Line 640-645 (`engine/main.py`)**: Rate limiter checks `_last_alert_time[symbol]` against 2-hour window
- **Line 647**: Alert only fires if `notifier.enabled AND cooldown_expired`
- **Result**: First BUY signal on a symbol fires an alert; next 27 BUYs on that symbol within 2 hours are silently suppressed with log: `"WhatsApp alert for {symbol} suppressed — cooldown active"`

## Evidence

### Alert Flow (Two Entry Points)
1. **Scheduler Watchlist Scan** (`main.py` ~510-677): Runs every 30 min, calls `_analyze_and_alert(symbol, is_futures)` → line 658: `await notifier.send(msg)`
2. **Manual `/scanner/run` POST** (`main.py` ~3190-3260): User-triggered manual scan → line 3236: `alert_sent = await notifier.send(msg)`

Both paths use **the same shared `_last_alert_time` dict** (line 217) and **the same 2-hour cooldown** (line 218, line 644, line 3225).

### Decision Table vs Alert Table Divergence
- **Decisions Table**: 28 rows on Apr 7 + 28 rows on Apr 8 (confirmed per earlier session notes)
- **Alert Log Table**: Only 20 rows in full history (per Apr 10 query), mostly `pending_approval` type, zero `trade_signal` type

**Interpretation**: Decisions go to DB unconditionally. Alerts go to WhatsApp **only if cooldown expires**. The 27 suppressed signals are logged at INFO level but not persisted to `alert_log` table.

### The Notifier Flow
- **`engine/notifications/whatsapp.py` line 49-52**: `enabled` flag checks for placeholder strings (`"your_account_sid_here"`, `None`, `""`)
- **Line 59-81**: `send()` method respects `self.enabled` flag; returns `False` if disabled
- **Line 196-201**: `get_notifier()` creates fresh instance each call, re-checks .env on every alert

**No TESTING_MODE flag found** — alerts would fire if Twilio credentials are present and cooldown expired.

## Hypotheses Tested & Resolved

| Hypothesis | Status | Evidence |
|-----------|--------|----------|
| H1: `notifier.enabled` False (bad config) | REJECTED | Twilio vars in .env per session notes; pending_approval alerts ARE working (line 33 in alert_log), proving Twilio is configured |
| H2: `ALERT_COOLDOWN_HOURS` too high | **CONFIRMED** | Set to 2 hours (hardcoded line 218); suppresses 27/28 consecutive BUYs per symbol |
| H3: TESTING_MODE flag suppresses sends | REJECTED | No such flag found in codebase; pending_approval alerts fire |
| H4: Decisions use different path than alerts | REJECTED | Same rate limiter, same `_last_alert_time` dict |
| H5: `notifier.send()` not awaited | REJECTED | Line 658 & 3236 both use `await` |
| H6: Twilio silently failing | POSSIBLE BUT SECONDARY | Alert_log shows no `trade_signal` entries; only pending_approval logged. If Twilio were down, alerts would appear in alert_log as `status='failed'`. They don't appear at all, meaning **cooldown is preventing the call before Twilio is even contacted**. |

## Code Locations

| Component | Path | Lines | Issue |
|-----------|------|-------|-------|
| Cooldown constant | `engine/main.py` | 218 | Hardcoded 2h, no .env override |
| Scheduler alert check | `engine/main.py` | 640-647 | Rate limit applied before send |
| Manual scan alert check | `engine/main.py` | 3221-3227 | Same rate limit |
| Suppressed log (no alert_log entry) | `engine/main.py` | 664-668 | Logs to console but not DB |
| Notifier enable check | `engine/notifications/whatsapp.py` | 49-52 | Works correctly |
| Notifier send | `engine/notifications/whatsapp.py` | 59-81 | Works correctly |

## Phase 1 Recommended Fix

**URGENT (P0):** The current design makes it impossible to validate WhatsApp alerts during dev/testing without manually resetting `_last_alert_time` dict between tests.

**Immediate Recommendation:**
1. Add `.env` override for cooldown: `ALERT_COOLDOWN_HOURS=0.5` (30 min for testing, 2h for production)
2. Persist suppressed alerts to `alert_log` with `status='suppressed'` + `error='cooldown_active'` for audit trail
3. Add `/health/alerts` endpoint to surface cooldown state and enable manual reset (non-prod only)

**Why this matters**: The 28 BUYs on Apr 7–8 prove the pipeline is working correctly (decisions were made), but the alert system silently dropped them because of this hardcoded 2-hour gate. In Phase 2 (live trading), this is critical operational feedback — you need to know every signal attempt, not just the first one per symbol.

## No Engine Restart Needed

This is a read-only audit. No code changes made.
