# WebSocket Real-Time Event Streaming

JARVIS TRADER now supports real-time event streaming via WebSocket for live dashboard updates without polling.

## Architecture Overview

### Backend (Python/FastAPI)

**Location**: `engine/websocket/`

- **`manager.py`**: `WebSocketManager` class
  - Tracks connected clients
  - Broadcasts events to all connected clients
  - Handles graceful disconnection
  - Thread-safe with async locks

- **`events.py`**: Event emitter functions
  - `emit_order_fill(order_data)`
  - `emit_kill_switch_change(active, reason)`
  - `emit_circuit_breaker(breaker_name, triggered, value)`
  - `emit_pipeline_complete(symbol, decision, timing)`
  - `emit_safety_event(event_type, details)`
  - `emit_price_update(symbol, price, bid, ask)`

### Frontend (TypeScript/React)

**Location**: `dashboard/lib/`

- **`use-websocket.ts`**: Custom React hook
  - Handles connection/reconnection with exponential backoff
  - Buffers last 100 events
  - Ping/pong keep-alive every 30 seconds
  - Automatic fallback on failure

- **`websocket-example.tsx`**: Example components
  - Shows how to integrate WebSocket in dashboard pages

## Event Structure

All WebSocket events follow this JSON format:

```json
{
  "type": "order_fill" | "kill_switch" | "circuit_breaker" | "pipeline_complete" | "safety_event" | "price_update",
  "data": { /* event-specific data */ },
  "timestamp": "2026-03-29T14:23:45.123456"
}
```

### Event Types

#### 1. `order_fill`
Emitted when an order is filled.

```json
{
  "type": "order_fill",
  "data": {
    "symbol": "MES",
    "quantity": 2,
    "price": 5432.50,
    "side": "BUY",
    "order_id": "abc123",
    "order_type": "limit"
  },
  "timestamp": "2026-03-29T14:23:45.123456"
}
```

#### 2. `kill_switch`
Emitted when kill switch state changes.

```json
{
  "type": "kill_switch",
  "data": {
    "active": true,
    "reason": "Daily loss limit exceeded",
    "action": "activated"
  },
  "timestamp": "2026-03-29T14:23:45.123456"
}
```

#### 3. `circuit_breaker`
Emitted when a circuit breaker is triggered.

```json
{
  "type": "circuit_breaker",
  "data": {
    "breaker_name": "daily_loss",
    "triggered": true,
    "value": -250.50
  },
  "timestamp": "2026-03-29T14:23:45.123456"
}
```

#### 4. `pipeline_complete`
Emitted when analysis pipeline finishes for a symbol.

```json
{
  "type": "pipeline_complete",
  "data": {
    "symbol": "MES",
    "decision": "buy",
    "timing": {
      "started_at": "2026-03-29T14:23:00.000000",
      "completed_at": "2026-03-29T14:23:45.123456",
      "elapsed_seconds": 45.123
    }
  },
  "timestamp": "2026-03-29T14:23:45.123456"
}
```

#### 5. `safety_event`
Emitted for safety/risk alerts.

```json
{
  "type": "safety_event",
  "data": {
    "event_type": "margin_warning",
    "details": {
      "symbol": "MES",
      "reason": "Position size exceeds limit",
      "current_value": 150000,
      "limit": 100000
    }
  },
  "timestamp": "2026-03-29T14:23:45.123456"
}
```

#### 6. `price_update`
Emitted for price updates (if configured to emit).

```json
{
  "type": "price_update",
  "data": {
    "symbol": "MES",
    "price": 5432.50,
    "bid": 5432.00,
    "ask": 5433.00
  },
  "timestamp": "2026-03-29T14:23:45.123456"
}
```

#### 7. `ping`
Keep-alive message sent by server every 30 seconds.

```json
{
  "type": "ping",
  "timestamp": "2026-03-29T14:23:45.123456"
}
```

## Backend Integration

### 1. Initialization (already done in `main.py`)

```python
from websocket.manager import WebSocketManager
from websocket.events import set_ws_manager

# In lifespan context manager:
ws_manager = WebSocketManager()
set_ws_manager(ws_manager)
```

### 2. WebSocket Endpoint (already added to `main.py`)

```
ws://localhost:8010/ws/events
```

Clients connect here to receive real-time events.

### 3. Status Endpoint

```
GET /ws/status
```

Returns:
```json
{
  "status": "ok",
  "connections": 5
}
```

### 4. Emitting Events

Events are already wired into:

- **Kill switch toggles** (`main.py`):
  ```python
  await emit_kill_switch_change(active=True, reason="Daily loss limit")
  ```

- **Pipeline completion** (`agents/pipeline.py`):
  ```python
  await emit_pipeline_complete(symbol, final_action, timing)
  ```

To add event emissions in other parts of the code:

```python
from websocket.events import emit_order_fill, emit_circuit_breaker

# Emit an order fill event
await emit_order_fill({
    "symbol": "MES",
    "quantity": 2,
    "price": 5432.50,
    "side": "BUY",
    "order_id": "abc123"
})

# Emit a circuit breaker event
await emit_circuit_breaker("daily_loss", triggered=True, value=-250.50)
```

## Frontend Integration

### Basic Usage

```typescript
'use client';

import { useWebSocket } from '@/lib/use-websocket';
import { useEffect } from 'react';

export function MyComponent() {
  const { isConnected, lastEvent, events } = useWebSocket();

  useEffect(() => {
    if (lastEvent?.type === 'order_fill') {
      console.log('Order filled!', lastEvent.data);
    }
  }, [lastEvent]);

  return (
    <div>
      <p>Connected: {isConnected ? 'Yes' : 'No'}</p>
      <p>Last Event: {lastEvent?.type}</p>
    </div>
  );
}
```

### Hook API

```typescript
interface UseWebSocketReturn {
  isConnected: boolean;              // True when connected
  lastEvent: WebSocketEvent | null;  // Most recent event
  events: WebSocketEvent[];          // Last 100 events
  connectionStatus: 'connected' | 'connecting' | 'disconnected';
  connectionAttempt: number;         // Current reconnection attempt
}

function useWebSocket(config?: {
  url?: string;                      // Defaults to ws://localhost:8010/ws/events
  autoConnect?: boolean;             // Defaults to true
  reconnectOnClose?: boolean;        // Defaults to true
  maxReconnectAttempts?: number;     // Defaults to 10
  initialReconnectDelay?: number;    // Defaults to 1000ms
  maxReconnectDelay?: number;        // Defaults to 30000ms
}): UseWebSocketReturn
```

### Reconnection Logic

The hook uses exponential backoff with jitter:

1. First disconnect: retry after 1s
2. If still fails: retry after 2s
3. Then: 4s, 8s, 16s, etc. (capped at 30s)
4. After 10 failed attempts: give up

The delay resets to 1s on successful reconnection.

### Examples

See `dashboard/lib/websocket-example.tsx` for complete examples of:

- `OrderFillMonitor` - Track order fills in real-time
- `KillSwitchMonitor` - Alert on kill switch changes
- `CircuitBreakerMonitor` - Monitor circuit breaker triggers
- `PipelineMonitor` - Watch pipeline completions
- `PriceUpdateMonitor` - Track price updates
- `EventLog` - Display all events (useful for debugging)

## Deployment Notes

### Local Development

WebSocket works out-of-the-box when:
- Backend runs on `http://localhost:8010`
- Frontend runs on `http://localhost:3010` or `http://localhost:3000`
- CORS is configured (already done in `main.py`)

### Production

For production deployments:

1. **HTTPS/WSS**: WebSocket connections over HTTPS must use `wss://` (secure WebSocket)
   - Update `use-websocket.ts` to use `wss://` for secure connections
   - Ensure backend serves WSS on the same domain

2. **Load Balancing**: If using a load balancer/reverse proxy:
   - Ensure WebSocket upgrades are supported
   - Check connection timeout settings (default 30s ping keeps it alive)
   - Session affinity may be needed if using multiple backends

3. **Firewall**: Ensure port 8010 (or your production port) allows WebSocket connections

### Nginx Example

```nginx
location /ws/ {
    proxy_pass http://localhost:8010;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```

## Performance & Best Practices

### Data Volume
- Each connection receives ALL events (no filtering)
- For many connections, consider implementing server-side filtering
- Currently no authentication on WebSocket endpoint (add if needed)

### Client-Side
- Hook buffers 100 events in memory
- Older events are discarded
- For archiving, save to IndexedDB or send to backend API

### Server-Side
- Manager uses async locks for thread-safety
- Failed sends automatically remove disconnected clients
- Graceful degradation if WebSocket unavailable

### Monitoring
Check WebSocket health:

```bash
# Check connected clients
curl http://localhost:8010/ws/status
# Response: {"status": "ok", "connections": 5}
```

## Fallback to Polling

If WebSocket is unavailable or fails:

1. Dashboard automatically falls back to SWR polling
2. Existing API endpoints continue to work normally
3. Real-time updates just become polling-based (5-10s latency vs instant)

To implement a fallback in your component:

```typescript
const { isConnected, lastEvent } = useWebSocket();

// Fallback to polling if WebSocket not connected
const { data: polledData } = useSWR(
  !isConnected ? '/api/engine/health' : null,
  fetcher,
  { refreshInterval: 5000 }
);
```

## Troubleshooting

### Connection fails immediately
1. Check backend is running: `curl http://localhost:8010/health`
2. Check firewall allows port 8010
3. Check CORS settings in `main.py`

### Connection drops frequently
1. Check for proxy timeouts (increase to 60+ seconds)
2. Monitor server logs for errors
3. Verify network stability

### Events not received
1. Check WebSocket is connected: `isConnected === true`
2. Verify event is being emitted (check backend logs)
3. Check browser console for JS errors

### Memory usage increasing
1. Hook buffers 100 events - memory is bounded
2. If long-running, clear old events periodically
3. Monitor with browser DevTools

## Debugging

### Enable verbose logging (browser console)

The hook logs to console with `[WebSocket]` prefix. Set browser console filter to see all messages:

```
[WebSocket]
```

### Check event stream

```typescript
const { events } = useWebSocket();
console.log(events); // All 100 most recent events
```

### Monitor server-side

```bash
# Watch logs for WebSocket events
tail -f logs/jarvis_trader.log | grep -i websocket
```

## Future Enhancements

Potential improvements:
- [ ] Event filtering/subscription (subscribe only to certain event types)
- [ ] Compression (message size optimization)
- [ ] Authentication (API key in WebSocket handshake)
- [ ] Binary protocol (more efficient than JSON)
- [ ] Event ordering guarantees
- [ ] Delivery confirmation/acknowledgment
