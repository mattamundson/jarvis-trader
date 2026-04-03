# Consecutive Loss Tracking & Position Sizing

## Overview

The **ConsecutiveLossTracker** is a critical safety feature in JARVIS TRADER that automatically reduces position sizes after consecutive losing trades and halts trading entirely if losses reach dangerous levels.

This feature is **hardcoded in Python** — no LLM reasoning. All position size reductions follow deterministic rules enforced by the SafetyLayer before any order reaches the broker.

## Architecture

### Components

1. **ConsecutiveLossTracker** (`engine/risk/loss_tracker.py`)
   - Tracks consecutive losses per symbol and globally
   - Persists state to `engine/data/loss_tracker.json` (survives app restarts)
   - Implements position sizing reduction rules
   - Manages 24-hour trading halt

2. **SafetyLayer Integration** (`engine/risk/safety_layer.py`)
   - Wires loss tracker into `check_order()` method
   - Reduces order quantities based on loss streak
   - Rejects orders when halt is active
   - Records trade results via API

3. **Configuration** (`engine/config.py`)
   - `CONSECUTIVE_LOSS_HALF_SIZE` (default: 3)
   - `CONSECUTIVE_LOSS_QUARTER_SIZE` (default: 5)
   - `CONSECUTIVE_LOSS_HALT` (default: 7)
   - `CONSECUTIVE_LOSS_HALT_HOURS` (default: 24)

## Position Sizing Rules

Position size is reduced based on **global consecutive losses**:

| Losses | Position Size | Description |
|--------|---------------|------------|
| 0-2    | 1.0x (100%)   | Normal trading |
| 3      | 0.5x (50%)    | Half size - reduce risk |
| 5      | 0.25x (25%)   | Quarter size - severe restriction |
| 7+     | 0.0x (0%)     | **HALT** - no trading for 24 hours |

### Reset Condition

A **single winning trade** resets the global loss counter to 0, immediately returning to normal position sizing.

## API Endpoints

### Get Loss Tracker Status
```
GET /safety/loss-tracker
```

Returns comprehensive status:
```json
{
  "enabled": true,
  "global_consecutive_losses": 3,
  "symbol_losses": {
    "MES": 2,
    "MNQ": 1
  },
  "position_size_multiplier": 0.5,
  "is_halted": false,
  "halt_until": null,
  "last_trade_symbol": "MNQ",
  "last_trade_timestamp": "2026-03-29T15:45:30.123456+00:00",
  "config": {
    "consecutive_loss_half_size": 3,
    "consecutive_loss_quarter_size": 5,
    "consecutive_loss_halt": 7,
    "consecutive_loss_halt_hours": 24
  }
}
```

### Record Trade Result
```
POST /safety/loss-tracker/record?symbol=MES&pnl=-150.0
```

Manually record a trade result (useful for testing). Returns updated status.

### Reset Loss Tracker
```
POST /safety/loss-tracker/reset?symbol=MES  # Optional: reset specific symbol
```

Manually reset loss counters (human intervention). Clears halt timer if active.

## Usage in Code

### Record a Trade Result

```python
# From trader agent or risk manager
safety_layer.record_trade_result("MES", -150.0)  # Loss
safety_layer.record_trade_result("MES", 200.0)   # Win (resets counter)
```

### Check Loss Tracker Status

```python
status = safety_layer.get_loss_tracker_status()
print(f"Consecutive losses: {status['global_consecutive_losses']}")
print(f"Position multiplier: {status['position_size_multiplier']}")
print(f"Is halted: {status['is_halted']}")
```

### Manually Reset (Human Review)

```python
# Reset global counter
safety_layer.reset_loss_tracker()

# Reset symbol-specific counter
safety_layer.reset_loss_tracker(symbol="MES")
```

## Order Flow with Loss Tracking

1. **Order Request** arrives at `SafetyLayer.check_order()`

2. **All standard checks** pass (daily loss limit, drawdown, position size, etc.)

3. **Loss tracker check**:
   - If halted: **REJECT** with "Consecutive loss limit reached (N losses) — trading paused for 24 hours"
   - If multiplier < 1.0: **REDUCE** order quantity and emit warning

4. **Execution**: Order proceeds to broker with adjusted quantity

## State Persistence

Loss tracking state is persisted to `engine/data/loss_tracker.json`:

```json
{
  "global_consecutive_losses": 3,
  "symbol_losses": {
    "MES": 2,
    "MNQ": 1
  },
  "last_trade_symbol": "MES",
  "last_trade_timestamp": "2026-03-29T15:45:30.123456+00:00",
  "halt_until": null
}
```

This allows loss tracking to survive application restarts — the state is automatically reloaded on startup.

## Trade Recording Integration

The loss tracker must be called **after trades close** with realized P&L. This is typically done by:

1. **Risk Manager Agent** (after position is closed)
2. **Trader Agent** (reporting closed P&L)
3. **Manual API Call** (for testing/retroactive recording)

Example flow:
```
1. Trader opens MES position (risk score: bullish)
2. Market moves against trade
3. Position closed with -$150 P&L
4. Risk Manager calls: safety_layer.record_trade_result("MES", -150.0)
5. Loss counter increments: 1 consecutive loss
6. Next order quantity reduced (if threshold reached)
```

## Configuration Examples

### Conservative (Maximum Safety)
```python
CONSECUTIVE_LOSS_HALF_SIZE = 2      # Reduce after 2 losses
CONSECUTIVE_LOSS_QUARTER_SIZE = 4   # Quarter size after 4 losses
CONSECUTIVE_LOSS_HALT = 6           # Halt after 6 losses
CONSECUTIVE_LOSS_HALT_HOURS = 24    # 24-hour halt
```

### Moderate (Balanced)
```python
CONSECUTIVE_LOSS_HALF_SIZE = 3      # (default)
CONSECUTIVE_LOSS_QUARTER_SIZE = 5   # (default)
CONSECUTIVE_LOSS_HALT = 7           # (default)
CONSECUTIVE_LOSS_HALT_HOURS = 24    # (default)
```

### Aggressive (More Trading)
```python
CONSECUTIVE_LOSS_HALF_SIZE = 4      # Reduce after 4 losses
CONSECUTIVE_LOSS_QUARTER_SIZE = 6   # Quarter size after 6 losses
CONSECUTIVE_LOSS_HALT = 10          # Halt after 10 losses
CONSECUTIVE_LOSS_HALT_HOURS = 12    # 12-hour halt
```

## Testing

Run the validation script to verify all components:

```bash
cd engine/
python3 validate_loss_tracker_simple.py
```

Expected output:
```
======================================================================
CONSECUTIVE LOSS TRACKER VALIDATION
======================================================================

=== Test 1: Basic Functionality ===
✅ Initial state correct
✅ Single loss recorded
✅ Position size reduction triggered at 3 losses
✅ Win resets counter correctly

=== Test 2: Multiplier Thresholds ===
✅ 0-2 losses: 1.0x ✓
✅ 3 losses: 0.5x ✓
✅ 4 losses: 0.5x ✓
✅ 5 losses: 0.25x ✓
✅ 6 losses: 0.25x ✓
✅ 7 losses: 0.0x (HALTED) ✓

... (more tests)

======================================================================
RESULTS: 7 passed, 0 failed
======================================================================

🎉 All tests passed!
```

## Safety Guarantees

1. **Deterministic Rules**: No LLM can override position size reductions or halt
2. **Persistent State**: Loss tracking survives application restarts
3. **Per-Symbol Tracking**: Each instrument tracked separately for informed decisions
4. **Hard Limits**: Trading halt (0.0x multiplier) blocks all orders
5. **Human Override**: Only humans (Matt) can manually reset counters

## Example Scenarios

### Scenario 1: Gradual Loss Streak

```
Trade 1: MES -$100 (loss 1)    → 1.0x position size
Trade 2: MES -$75  (loss 2)    → 1.0x position size
Trade 3: MES -$50  (loss 3)    → 0.5x position size (REDUCED)
Trade 4: MNQ -$30  (loss 4)    → 0.5x position size
Trade 5: MES +$200 (WIN)       → 0.0 consecutive losses → 1.0x position size
```

### Scenario 2: Hitting the Halt

```
Trade 1-6: Various losses      → Counters at 6, size at 0.25x
Trade 7: Another loss          → Counter at 7 → HALT ACTIVATED
Trade 8 (attempted): MES order → REJECTED: "Consecutive loss limit reached (7 losses) — trading paused for 24 hours"
```

After 24 hours:
```
Trade 8: MES order (next day)  → ACCEPTED (halt period expired)
```

## See Also

- `engine/risk/safety_layer.py` — Main safety gate
- `engine/risk/pnl_monitor.py` — Daily P&L tracking
- `engine/config.py` — Configuration settings
- `engine/main.py` — API endpoints
- `tests/test_loss_tracker.py` — Full test suite
