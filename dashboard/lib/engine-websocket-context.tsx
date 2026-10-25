"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { WsEvent } from "@/hooks/ws-types";

export type WsSubscriber = (event: WsEvent) => void;

export interface EngineWebSocketContextValue {
  isConnected: boolean;
  lastEvent: WsEvent | null;
  subscribe: (handler: WsSubscriber) => () => void;
  /** Manual reconnect (re-runs connection logic after close). */
  connect: () => void;
  /** Close socket and stop auto-reconnect until next connect(). */
  disconnect: () => void;
}

export const EngineWebSocketContext =
  createContext<EngineWebSocketContextValue | null>(null);

function resolveEngineHttpUrl(url?: string): string {
  if (url) return url;
  if (process.env.NEXT_PUBLIC_ENGINE_URL) return process.env.NEXT_PUBLIC_ENGINE_URL;
  if (typeof window !== "undefined") {
    // Route WS through the same-origin Next.js proxy so the /ws/events rewrite
    // in next.config.ts injects the ENGINE_API_KEY server-side. Direct engine
    // connections cannot carry the key in a browser WebSocket constructor.
    return window.location.origin;
  }
  // 127.0.0.1, not localhost: Windows resolves localhost to ::1 first and the
  // engine binds IPv4 only.
  return "http://127.0.0.1:8010";
}

/**
 * Single shared WebSocket to the engine `/ws/events` stream.
 * Mount once near the root (inside client tree) so all `useWebSocket` hooks share one connection.
 */
export function EngineWebSocketProvider({
  children,
  url,
}: {
  children: React.ReactNode;
  url?: string;
}) {
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<WsEvent | null>(null);
  const subscribersRef = useRef(new Set<WsSubscriber>());
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef(true);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const attemptRef = useRef(0);
  const connectImplRef = useRef<(() => void) | null>(null);

  const subscribe = useCallback((handler: WsSubscriber) => {
    subscribersRef.current.add(handler);
    return () => {
      subscribersRef.current.delete(handler);
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const broadcast = (event: WsEvent) => {
      setLastEvent(event);
      subscribersRef.current.forEach((h) => {
        try {
          h(event);
        } catch (e) {
          console.error("[EngineWebSocket] subscriber error:", e);
        }
      });
    };

    const connect = () => {
      if (wsRef.current?.readyState === WebSocket.OPEN) return;
      try {
        const engineHttp = resolveEngineHttpUrl(url);
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
            broadcast(flat);
          } catch {
            /* ignore parse errors */
          }
        };
        ws.addEventListener("close", () => {
          setConnected(false);
          if (!reconnectRef.current) return;
          attemptRef.current += 1;
          reconnectTimer.current = setTimeout(
            () => connect(),
            Math.min(1000 * Math.pow(2, attemptRef.current), 30000)
          );
        });
        wsRef.current = ws;
      } catch (err) {
        console.error("WebSocket connection error:", err);
      }
    };

    connectImplRef.current = connect;
    reconnectRef.current = true;
    connect();

    return () => {
      reconnectRef.current = false;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      setConnected(false);
    };
  }, [url]);

  const connect = useCallback(() => {
    reconnectRef.current = true;
    attemptRef.current = 0;
    connectImplRef.current?.();
  }, []);

  const disconnect = useCallback(() => {
    reconnectRef.current = false;
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setConnected(false);
  }, []);

  const value = useMemo(
    () => ({
      isConnected: connected,
      lastEvent,
      subscribe,
      connect,
      disconnect,
    }),
    [connected, lastEvent, subscribe, connect, disconnect]
  );

  return (
    <EngineWebSocketContext.Provider value={value}>
      {children}
    </EngineWebSocketContext.Provider>
  );
}

export function useEngineWebSocketContext(): EngineWebSocketContextValue {
  const ctx = useContext(EngineWebSocketContext);
  if (!ctx) {
    throw new Error(
      "useEngineWebSocketContext must be used within EngineWebSocketProvider"
    );
  }
  return ctx;
}
