'use client';

import { useEffect, useRef, useState, useCallback } from 'react';

export interface WebSocketEvent {
  type: 'order_fill' | 'kill_switch' | 'circuit_breaker' | 'pipeline_complete' | 'safety_event' | 'price_update' | 'ping';
  data: Record<string, any>;
  timestamp: string;
}

export interface UseWebSocketReturn {
  isConnected: boolean;
  lastEvent: WebSocketEvent | null;
  events: WebSocketEvent[];
  connectionStatus: 'connected' | 'connecting' | 'disconnected';
  connectionAttempt: number;
}

interface WebSocketManagerConfig {
  url?: string;
  autoConnect?: boolean;
  reconnectOnClose?: boolean;
  maxReconnectAttempts?: number;
  initialReconnectDelay?: number;
  maxReconnectDelay?: number;
}

/**
 * Hook for WebSocket real-time event streaming from JARVIS TRADER backend.
 *
 * Handles:
 * - Automatic connection/reconnection with exponential backoff
 * - Event buffering (keeps last 100 events)
 * - Graceful fallback on connection failure
 * - Ping/pong keep-alive
 *
 * Usage:
 * ```typescript
 * const { isConnected, lastEvent, events } = useWebSocket({
 *   url: 'ws://localhost:8010/ws/events',
 *   autoConnect: true,
 * });
 *
 * useEffect(() => {
 *   if (lastEvent?.type === 'order_fill') {
 *     console.log('Order filled:', lastEvent.data);
 *   }
 * }, [lastEvent]);
 * ```
 */
export function useWebSocket(config: WebSocketManagerConfig = {}): UseWebSocketReturn {
  const {
    url = 'ws://localhost:8010/ws/events',
    autoConnect = true,
    reconnectOnClose = true,
    maxReconnectAttempts = 10,
    initialReconnectDelay = 1000, // 1 second
    maxReconnectDelay = 30000, // 30 seconds
  } = config;

  const wsRef = useRef<WebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<WebSocketEvent | null>(null);
  const [events, setEvents] = useState<WebSocketEvent[]>([]);
  const [connectionStatus, setConnectionStatus] = useState<'connected' | 'connecting' | 'disconnected'>('disconnected');
  const [connectionAttempt, setConnectionAttempt] = useState(0);

  const reconnectDelayRef = useRef(initialReconnectDelay);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isMountedRef = useRef(true);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      console.log('[WebSocket] Already connected');
      return;
    }

    // Check if we've exceeded max reconnect attempts
    if (connectionAttempt >= maxReconnectAttempts && connectionAttempt > 0) {
      console.warn('[WebSocket] Max reconnection attempts reached, giving up');
      setConnectionStatus('disconnected');
      return;
    }

    if (!isMountedRef.current) return;

    setConnectionStatus('connecting');

    try {
      console.log(`[WebSocket] Connecting to ${url} (attempt ${connectionAttempt + 1}/${maxReconnectAttempts})`);
      const ws = new WebSocket(url);

      ws.onopen = () => {
        if (!isMountedRef.current) return;
        console.log('[WebSocket] Connected');
        setIsConnected(true);
        setConnectionStatus('connected');
        setConnectionAttempt(0);
        reconnectDelayRef.current = initialReconnectDelay; // Reset delay on successful connection

        // Set up ping interval (every 30 seconds)
        if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
          }
        }, 30000);
      };

      ws.onmessage = (event) => {
        if (!isMountedRef.current) return;

        try {
          const message = JSON.parse(event.data) as WebSocketEvent;

          // Skip ping/pong frames
          if (message.type === 'ping') {
            console.debug('[WebSocket] Ping received, sending pong');
            // Optionally send pong back
            return;
          }

          console.debug('[WebSocket] Event received:', message.type);
          setLastEvent(message);

          // Keep last 100 events
          setEvents((prev) => {
            const updated = [message, ...prev];
            return updated.slice(0, 100);
          });
        } catch (e) {
          console.error('[WebSocket] Failed to parse message:', e);
        }
      };

      ws.onerror = (error) => {
        if (!isMountedRef.current) return;
        console.error('[WebSocket] Error:', error);
        // Error typically precedes close, so we let close handle reconnection
      };

      ws.onclose = () => {
        if (!isMountedRef.current) return;
        console.log('[WebSocket] Disconnected');
        setIsConnected(false);
        setConnectionStatus('disconnected');

        // Clear ping interval
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
          pingIntervalRef.current = null;
        }

        // Attempt reconnection with exponential backoff
        if (reconnectOnClose && connectionAttempt < maxReconnectAttempts) {
          const delay = Math.min(reconnectDelayRef.current * Math.pow(2, connectionAttempt), maxReconnectDelay);
          console.log(`[WebSocket] Reconnecting in ${delay}ms...`);

          if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
          reconnectTimeoutRef.current = setTimeout(() => {
            if (isMountedRef.current) {
              setConnectionAttempt((prev) => prev + 1);
            }
          }, delay);
        }
      };

      wsRef.current = ws;
    } catch (e) {
      console.error('[WebSocket] Connection error:', e);
      setConnectionStatus('disconnected');
    }
  }, [url, connectionAttempt, maxReconnectAttempts, initialReconnectDelay, maxReconnectDelay]);

  // Auto-connect on mount
  useEffect(() => {
    if (autoConnect && connectionStatus === 'disconnected' && connectionAttempt === 0) {
      connect();
    }
  }, [autoConnect, connectionStatus, connectionAttempt, connect]);

  // Trigger reconnection when connectionAttempt changes
  useEffect(() => {
    if (connectionAttempt > 0 && isMountedRef.current) {
      connect();
    }
  }, [connectionAttempt, connect]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.close();
      }
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
    };
  }, []);

  return {
    isConnected,
    lastEvent,
    events,
    connectionStatus,
    connectionAttempt,
  };
}
