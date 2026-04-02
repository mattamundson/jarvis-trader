"use client";
import { useEffect, useRef, useCallback, useState } from "react";

export type WsEvent =
  | { type: "price_update"; symbol: string; price: number; timestamp: string }
  | { type: "pipeline_complete"; symbol: string; action: string; confidence: number }
  | { type: "kill_switch"; active: boolean }
  | { type: "circuit_breaker"; reason: string }
  | { type: "order_fill"; symbol: string; action: string; price: number; quantity: number }
  | { type: "safety_event"; message: string };

type WsEventHandler = (event: WsEvent) => void;

export function useWebSocket(onEvent?: WsEventHandler) {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<WsEvent | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const connect = useCallback(() => {
    if (typeof window === "undefined") return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const engineHttp = process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://localhost:8010";
      const engineWs = engineHttp.replace(/^http/, "ws");
      const ws = new WebSocket(`${engineWs}/ws/events`);

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        try {
          const data: WsEvent = JSON.parse(event.data);
          setLastEvent(data);
          onEventRef.current?.(data);
        } catch {
          // ignore malformed messages
        }
      };

      ws.onclose = () => {
        setConnected(false);
        // Reconnect after 5 seconds
        setTimeout(() => {
          if (wsRef.current === ws) connect();
        }, 5_000);
      };

      ws.onerror = () => ws.close();

      wsRef.current = ws;
    } catch {
      setConnected(false);
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      const ws = wsRef.current;
      if (ws) {
        wsRef.current = null;
        ws.close();
      }
    };
  }, [connect]);

  return { connected, lastEvent };
}
