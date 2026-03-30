'use client';

/**
 * WebSocket Integration Example
 * =============================
 *
 * This file demonstrates how to integrate the useWebSocket hook
 * into your dashboard components.
 *
 * The hook automatically:
 * - Connects to ws://localhost:8010/ws/events
 * - Reconnects with exponential backoff on disconnect
 * - Buffers the last 100 events
 * - Sends ping/pong keep-alive every 30 seconds
 * - Falls back to polling if WebSocket fails
 *
 * To use this in a real component, import and add to your JSX:
 *
 * ```typescript
 * import { useWebSocket } from '@/lib/use-websocket';
 *
 * export function RealTimeUpdates() {
 *   const { isConnected, lastEvent, events } = useWebSocket();
 *
 *   return (
 *     <div>
 *       <div className="mb-4">
 *         <span className={isConnected ? 'text-green-600' : 'text-red-600'}>
 *           {isConnected ? 'Connected' : 'Disconnected'}
 *         </span>
 *       </div>
 *
 *       {lastEvent && (
 *         <div className="border p-4 mb-4 rounded bg-blue-50">
 *           <h3 className="font-bold">{lastEvent.type}</h3>
 *           <pre className="text-sm mt-2">
 *             {JSON.stringify(lastEvent, null, 2)}
 *           </pre>
 *         </div>
 *       )}
 *     </div>
 *   );
 * }
 * ```
 */

import { useEffect } from 'react';
import { useWebSocket, type WebSocketEvent } from './use-websocket';

/**
 * Example: Real-time order fill notifications
 */
export function OrderFillMonitor() {
  const { isConnected, lastEvent } = useWebSocket();

  useEffect(() => {
    if (lastEvent?.type === 'order_fill') {
      const data = lastEvent.data;
      console.log('Order filled:', {
        symbol: data.symbol,
        quantity: data.quantity,
        price: data.price,
        orderId: data.order_id,
      });

      // Update your UI, show toast notification, etc.
    }
  }, [lastEvent]);

  return (
    <div>
      <div className={`indicator ${isConnected ? 'connected' : 'disconnected'}`}>
        {isConnected ? 'Live' : 'Offline'}
      </div>
    </div>
  );
}

/**
 * Example: Kill switch state monitoring
 */
export function KillSwitchMonitor() {
  const { lastEvent } = useWebSocket();

  useEffect(() => {
    if (lastEvent?.type === 'kill_switch') {
      const { active, reason } = lastEvent.data;
      if (active) {
        console.warn('KILL SWITCH ACTIVATED:', reason);
        // Show urgent alert to user
      } else {
        console.log('Kill switch deactivated');
      }
    }
  }, [lastEvent]);

  return null; // This is a monitoring component
}

/**
 * Example: Circuit breaker alerts
 */
export function CircuitBreakerMonitor() {
  const { lastEvent } = useWebSocket();

  useEffect(() => {
    if (lastEvent?.type === 'circuit_breaker') {
      const { breaker_name, triggered, value } = lastEvent.data;
      if (triggered) {
        console.warn(`CIRCUIT BREAKER: ${breaker_name} triggered`, { value });
        // Show alert
      }
    }
  }, [lastEvent]);

  return null;
}

/**
 * Example: Pipeline completion notifications
 */
export function PipelineMonitor() {
  const { lastEvent } = useWebSocket();

  useEffect(() => {
    if (lastEvent?.type === 'pipeline_complete') {
      const { symbol, decision, timing } = lastEvent.data;
      console.log(`Pipeline completed for ${symbol}:`, {
        decision,
        elapsed_seconds: timing.elapsed_seconds,
      });
      // Update watchlist display, show new analysis result, etc.
    }
  }, [lastEvent]);

  return null;
}

/**
 * Example: Real-time price updates (if emitted)
 */
export function PriceUpdateMonitor() {
  const { lastEvent } = useWebSocket();

  useEffect(() => {
    if (lastEvent?.type === 'price_update') {
      const { symbol, price, bid, ask } = lastEvent.data;
      console.log(`${symbol} price updated: ${price} (bid: ${bid}, ask: ${ask})`);
      // Update price displays
    }
  }, [lastEvent]);

  return null;
}

/**
 * Example: All events display (useful for debugging)
 */
export function EventLog() {
  const { isConnected, events, connectionStatus, connectionAttempt } = useWebSocket();

  return (
    <div className="border rounded p-4 bg-gray-50">
      <div className="mb-4 flex items-center gap-4">
        <div>
          <span className="text-sm font-semibold">Connection:</span>
          <span
            className={`ml-2 text-sm font-bold ${
              isConnected ? 'text-green-600' : 'text-red-600'
            }`}
          >
            {connectionStatus}
          </span>
        </div>

        {connectionAttempt > 0 && (
          <div>
            <span className="text-sm font-semibold">Reconnect Attempt:</span>
            <span className="ml-2 text-sm">{connectionAttempt}</span>
          </div>
        )}
      </div>

      <div className="space-y-2">
        <h3 className="font-bold text-sm">Recent Events ({events.length}):</h3>
        <div className="max-h-96 overflow-y-auto space-y-1">
          {events.length === 0 ? (
            <p className="text-xs text-gray-500">No events yet...</p>
          ) : (
            events.map((event, idx) => (
              <div key={idx} className="text-xs border-l-2 border-blue-400 pl-2 py-1">
                <span className="font-semibold text-blue-600">{event.type}</span>
                <span className="text-gray-500 ml-2">
                  {new Date(event.timestamp).toLocaleTimeString()}
                </span>
                {event.type !== 'ping' && (
                  <pre className="text-xs mt-1 bg-white p-1 rounded max-w-sm overflow-x-auto">
                    {JSON.stringify(event.data, null, 2)}
                  </pre>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
