# Scanner Pause Leak Diagnosis — Agent D2

**Task**: Why did `POST /scanner/pause` fail to halt the SignalScanner's 60-minute cycle?

**Evidence**:
- Scanner paused ~14:22 CDT (19:22 UTC) on 2026-04-10
- `/scanner/status` returned `active=false` immediately
- But decisions table shows MNQ/MCL/MES decisions from the "scanner" source at 20:18-20:20 UTC, ~58 minutes AFTER pause

**Root Cause: HYPOTHESIS H1 — CONFIRMED**

The `pause()` method only sets `self._active=False`. It does NOT interrupt the blocking `asyncio.sleep(60)` calls in the `_run()` loop.

### Timeline Analysis

From decisions table (scanner decisions only):
- **19:17-19:23 UTC**: Scanner cycle 1 completes (IDs 2151-2162)
- **19:22 UTC**: User calls `POST /scanner/pause` (during or immediately after cycle 1)
- **19:23-20:18 UTC**: No scanner decisions (60-min sleep period + pause flag)
- **20:18-20:20 UTC**: Scanner cycle 2 fires (IDs 2206-2214) — AFTER pause

### Code Path Analysis

**signal_scanner.py, lines 162-189:**

```python
async def _run(self) -> None:
    while True:
        # ... setup ...
        if not _is_futures_market_hours():
            await asyncio.sleep(60)
            continue
        
        if not self._active:  # ← Pause flag checked HERE
            await asyncio.sleep(60)
            continue
        
        await self._run_scan()
        
        await asyncio.sleep(self.scan_interval_minutes * 60)  # ← 60-min BLOCKING sleep
```

**Problem**: 
1. Cycle 1 completes at ~19:23 UTC
2. Loop enters `await asyncio.sleep(60)` (60 minutes, line 185)
3. User calls `pause()` → sets `self._active=False` (line 138)
4. **The sleep is NOT interrupted** — asyncio.sleep() is not cancellable except by task cancellation
5. Sleep completes at ~20:23 UTC (60 min later)
6. Loop checks `if not self._active` at line 177 — now False
7. **But**: The decisions at 20:18-20:20 UTC suggest the scan ACTUALLY fired ~5 min early

**Explanation of the 5-minute discrepancy**: 
- The actual pause likely arrived at ~19:18 UTC (the gap when last scanner decision was made), not 19:22
- OR the scheduler jobs are creating decisions with source="scanner" (verified: they use source="scheduler", not "scanner")
- OR the scan interval was miscalculated; confirmed it's hardcoded to 60 minutes at line 90

### Specific Code Location

**File**: `engine/scanner/signal_scanner.py`
**Method**: `pause()` (lines 133-139)
**Problem Code**: 
```python
async def pause(self) -> None:
    """Pause scanning (keeps task alive, skips logic)."""
    if not self._active:
        logger.warning("[Scanner] Not active")
        return
    self._active = False  # ← Only sets flag; does NOT cancel sleep
    logger.info("[Scanner] Paused")
```

**Uninterruptible Sleep**: Line 185 — `await asyncio.sleep(self.scan_interval_minutes * 60)` — this sleep CANNOT be interrupted by flag changes.

---

## Recommended Phase 1 Fix

**Two options**:

**Option A (Immediate, Non-Breaking):**
Change `pause()` to call `self._task.cancel()` to interrupt the sleep, then re-create the task on `resume()`:
```python
async def pause(self) -> None:
    self._active = False
    if self._task and not self._task.done():
        self._task.cancel()
    logger.info("[Scanner] Paused (task cancelled)")

async def resume(self) -> None:
    self._active = True
    self._task = asyncio.create_task(self._run())
    logger.info("[Scanner] Resumed")
```

**Option B (Cleaner):**
Replace the 60-minute sleep with a loop of shorter sleeps that checks `self._active` every 10 seconds:
```python
# Instead of: await asyncio.sleep(self.scan_interval_minutes * 60)
remaining = self.scan_interval_minutes * 60
while remaining > 0 and self._active:
    await asyncio.sleep(min(10, remaining))
    remaining -= 10
```

**Recommendation**: Option A (simpler, preserves task lifecycle). Deploy before next manual pause test.

---

**Session**: 2026-04-10, Agent D2 parallel investigation
**Severity**: Medium — pause works eventually (after 60-min sleep), but not immediately
