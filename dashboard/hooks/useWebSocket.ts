"use client";
import { useEffect, useRef, useCallback, useState } from "react";

export type WsEvent =
  | { type: "price_update"; symbol: string; price: number; timestamp?: string }
  | { type: "pipeline_complete"; symbol: string; action: string; confidence: number; timestamp?: string }
  | { type: "kill_switch"; active: boolean; timestamp?: string }
  | { type: "circuit_breaker"; reason: string; timestamp?: string }
  | { type: "order_fill"; symbol: string; action: string; price: number; quantity: number; timestamp?: string }
  | { type: "safety_event"; message: string; timestamp?: string }
  | {
      type: "pending_approval_created";
      approval_id: string;
      symbol: string;
      final_action: string;
      timestamp?: string;
    }
  | { type: "ping" };

type WsEventHandler = (event: WsEvent) => void;

export function useWebSocket(url?: string, onEvent?: WsEventHandler) {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<WsEvent | null>(null);
  const onEventRef = useRef(onEvent);
  const reconnectRef = useRef(true);
  const reconnectTimer = useRef<NodeJS.Timeout>();
  const attemptRef = useRef(0);

  onEventRef.current = onEvent;

  const connect = useCallback(() => {
    if (typeof window === "undefined") return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const engineHttp = url || process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8010";
      const engineWs = engineHttp.replace(/^http/, "ws");
      const ws = new WebSocket(`${engineWs}/ws/events`);

      ws.onopen = () => {
        setConnected(true);
        attemptRef.current = 0;
      };

      ws.onmessage = (event) => {
        try {
          const raw = JSON.parse(event.data) as {
            type: string;
            data?: Record<string, unknown>;
            timestamp?: string;
          };
          if (raw.type === "ping") return;
          const flat = (
            raw.data != null
              ? { type: raw.type, ...raw.data, timestamp: raw.timestamp }
              : raw
          ) as WsEvent;
          setLastEvent(flat);
          onEventRef.current?.(flat);
        } catch {
          // Silently ignore parse errors
        }
      };

      ws.addEventListener("close", () => {
        setConnected(false);
        if (!reconnectRef.current) return;
        attemptRef.current++;
        reconnectTimer.current = setTimeout(
          () => connect(),
          Math.min(1000 * Math.pow(2, attemptRef.current), 30000)
        );
      });

      wsRef.current = ws;
    } catch (err) {
      // Connection error, will retry
      console.error("WebSocket connection error:", err);
    }
  }, [url]);

  const disconnect = useCallback(() => {
    reconnectRef.current = false;
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    if (wsRef.current) wsRef.current.close();
    setConnected(false);
  }, []);

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return { connect, disconnect, lastEvent, isConnected: connected };
}
