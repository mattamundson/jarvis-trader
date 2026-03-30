# WebSocket Integration Checklist

This document tracks the WebSocket integration status and provides guidance on adding event emissions to other parts of the system.

## Completed Implementations

### Backend

- [x] `engine/websocket/__init__.py` - Module exports
- [x] `engine/websocket/manager.py` - WebSocketManager class
- [x] `engine/websocket/events.py` - Event emitter functions
- [x] `engine/main.py` - WebSocket endpoint and manager initialization
- [x] Kill switch events wired in `engine/main.py`
- [x] Pipeline events wired in `engine/agents/pipeline.py`
- [x] WebSocket status endpoint `/ws/status`

### Frontend

- [x] `dashboard/lib/use-websocket.ts` - React hook with auto-reconnect
- [x] `dashboard/lib/api.ts` - Type definitions and status API
- [x] `dashboard/lib/websocket-example.tsx` - Example components

### Documentation

- [x] `WEBSOCKET.md` - Complete implementation guide
- [x] `WEBSOCKET_INTEGRATION_CHECKLIST.md` - This file

## To-Do: Additional Event Emissions

### 1. Safety Layer Circuit Breakers

**File**: `engine/risk/safety_layer.py`

When circuit breakers are triggered, emit events:

```python
# Add to imports:
from websocket.events import emit_circuit_breaker, emit_kill_switch_change

# In the method that activates kill switch on circuit breaker:
async def _check_circuit_breakers(self):
    # ... existing logic ...

    # When daily loss limit is breached:
    if daily_pnl_breached:
        await emit_circuit_breaker("daily_loss", triggered=True, value=daily_pnl)
        await emit_kill_switch_change(active=True, reason="Daily loss limit exceeded")

    # When max drawdown is breached:
    if drawdown_breached:
        await emit_circuit_breaker("max_drawdown", triggered=True, value=drawdown_pct)
        await emit_kill_switch_change(active=True, reason="Max drawdown exceeded")
```

### 2. Order Execution Events

**File**: `engine/execution/ib_order_manager.py` (or wherever orders are placed)

When orders fill or are placed:

```python
# Add to imports:
from websocket.events import emit_order_fill

# When order is filled:
async def on_order_fill(order_id, symbol, quantity, price, side):
    await emit_order_fill({
        "symbol": symbol,
        "quantity": quantity,
        "price": price,
        "side": side,
        "order_id": order_id,
        "order_type": "market",  # or the actual type
        "fill_time": datetime.now().isoformat()
    })
```

### 3. Price Update Events

**File**: `engine/data/market_data.py`

When market data is updated:

```python
# Add to imports:
from websocket.events import emit_price_update

# When price tick is received:
async def on_price_tick(symbol, price, bid, ask):
    # Only emit on significant changes or at interval:
    await emit_price_update(symbol, price, bid=bid, ask=ask)
```

### 4. Safety Events (Margin Warnings, etc.)

**File**: `engine/risk/pnl_monitor.py` or `engine/risk/safety_layer.py`

When warnings are triggered:

```python
# Add to imports:
from websocket.events import emit_safety_event

# When margin is running low:
if margin_available < min_margin_threshold:
    await emit_safety_event("margin_warning", {
        "current_margin": margin_available,
        "minimum_required": min_margin_threshold,
        "percentage": (margin_available / total_margin) * 100
    })

# When position size exceeds limit:
if position_size > max_position_size:
    await emit_safety_event("position_limit_exceeded", {
        "symbol": symbol,
        "current_size": position_size,
        "max_allowed": max_position_size
    })
```

## Integration Guide

### For Each Event Emission Point

1. **Import the emitter function** at the top of the file:
   ```python
   from websocket.events import emit_<event_type>
   ```

2. **Wrap in try-except** for robustness:
   ```python
   try:
       await emit_order_fill({...})
   except Exception as e:
       logger.error(f"Failed to emit event: {e}")
   ```

3. **Create async task** if not in async context:
   ```python
   asyncio.create_task(emit_order_fill({...}))
   ```

4. **Test locally** before deployment:
   - Check WebSocket connection in browser DevTools
   - Verify event appears in event stream
   - Confirm frontend handles event correctly

### Backtest/Test Context

For code that runs in backtest/test scenarios (not async):

```python
try:
    from websocket.events import emit_order_fill
    asyncio.create_task(emit_order_fill({...}))
except ImportError:
    # WebSocket not available in this context
    pass
except RuntimeError:
    # No running event loop (e.g., in tests)
    pass
```

## Testing the Integration

### 1. Manual WebSocket Connection Test

```bash
# Install wscat if needed:
npm install -g wscat

# Connect to WebSocket endpoint:
wscat -c ws://localhost:8010/ws/events

# Should receive ping messages every 30 seconds
```

### 2. Test Event Emission

```bash
# Activate kill switch via API and check WebSocket for event:
curl -X POST http://localhost:8010/safety/kill-switch/activate?reason=test

# In WebSocket terminal, should see:
{"type":"kill_switch","data":{"active":true,"reason":"test","action":"activated"},"timestamp":"..."}
```

### 3. Frontend Component Test

```typescript
// In browser console, test the hook directly:
import { useWebSocket } from '@/lib/use-websocket';

// Add to a test component:
const { isConnected, lastEvent, events } = useWebSocket();
console.log('Connected:', isConnected);
console.log('Last event:', lastEvent);
console.log('Event count:', events.length);
```

## Performance Monitoring

### Server-Side

Monitor WebSocket connections:

```bash
# Check active connections:
curl http://localhost:8010/ws/status

# Watch logs for WebSocket activity:
tail -f logs/jarvis_trader.log | grep -i websocket
```

### Client-Side

Monitor in browser DevTools:

```typescript
// Get WebSocket status from any component:
const status = await fetch('/api/engine/ws/status').then(r => r.json());
console.log(`Active connections: ${status.connections}`);
```

## Migration Guide (if needed)

If transitioning dashboard from polling to WebSocket:

1. **Add useWebSocket hook** to page that needs real-time updates
2. **Keep SWR queries as fallback** (no polling if WebSocket connected)
3. **Test both pathways** (WebSocket + polling)
4. **Gradual rollout** - enable for specific pages first
5. **Monitor connection stability** before full rollout

Example:

```typescript
export function DataPage() {
  const { isConnected, lastEvent } = useWebSocket();

  // Use WebSocket data if connected, otherwise poll
  const { data, isLoading } = useSWR(
    !isConnected ? '/api/engine/portfolio/status' : null,
    fetcher,
    { refreshInterval: isConnected ? 0 : 5000 }
  );

  if (lastEvent?.type === 'order_fill') {
    // Real-time update from WebSocket
    updateUI(lastEvent.data);
  }
}
```

## Debugging Checklist

If WebSocket events are not appearing:

- [ ] Backend is running on port 8010
- [ ] WebSocket manager initialized (check logs for "✅ WebSocket manager initialized")
- [ ] Event emission code is actually being executed
- [ ] Try/except not silently swallowing errors (check logs)
- [ ] Browser WebSocket connection is open (check Network tab)
- [ ] CORS headers correct
- [ ] Firewall allows port 8010

## Security Notes

Current implementation:

- No authentication on WebSocket endpoint
- All connected clients receive all events
- Events include potentially sensitive data (order details, PnL, etc.)

For production, consider:

1. **Add authentication**: Verify API key in WebSocket handshake
2. **Filter by user/account**: Only send relevant events
3. **Rate limiting**: Limit event emission frequency
4. **Encryption**: Use WSS (WebSocket Secure) over HTTPS only
5. **Access control**: Limit who can connect

## Future Enhancements

Potential improvements:

- [ ] Event filtering/subscription system (client chooses event types)
- [ ] Binary protocol for smaller payload size
- [ ] Event acknowledgment (client confirms receipt)
- [ ] Priority queuing (urgent events first)
- [ ] Persistent event history
- [ ] Message compression

## Status Dashboard

Current implementation provides:

- ✅ Real-time kill switch events
- ✅ Real-time pipeline completion events
- ✅ Auto-reconnect with exponential backoff
- ✅ Keep-alive ping/pong
- ✅ Event buffering (100 events)
- ✅ Example components
- ⭕ Circuit breaker events (ready to add)
- ⭕ Order fill events (ready to add)
- ⭕ Price update events (ready to add)
- ⭕ Safety/margin events (ready to add)

## Questions?

Refer to `WEBSOCKET.md` for complete documentation.
