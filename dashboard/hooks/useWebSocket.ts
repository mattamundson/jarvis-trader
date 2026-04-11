"use client";

import {
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { EngineWebSocketContext } from "@/lib/engine-websocket-context";
import type { WsEvent } from "./ws-types";

export type { WsEvent } from "./ws-types";

type WsEventHandler = (event: WsEvent) => void;

function resolveEngineHttpUrl(url?: string): string {
  if (url) return url;
  if (process.env.NEXT_PUBLIC_ENGINE_URL) return process.env.NEXT_PUBLIC_ENGINE_URL;
  if (typeof window !== "undefined") {
    // In the browser we connect back to the dashboard origin and let the
    // Next.js /ws rewrite proxy the upgrade to the engine.
    return window.location.origin;
  }
  return "http://localhost:8010";
}

/**
 * Subscribe to the shared engine WebSocket (when `EngineWebSocketProvider` is mounted)
 * or open a dedicated connection as a fallback when the provider is absent.
 */
export function useWebSocket(url?: string, onEvent?: WsEventHandler) {
  const ctx = useContext(EngineWebSocketContext);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const [legacyConnected, setLegacyConnected] = useState(false);
  const [legacyLastEvent, setLegacyLastEvent] = useState<WsEvent | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef(true);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const attemptRef = useRef(0);

  useEffect(() => {
    if (!ctx) return;
    return ctx.subscribe((e) => {
      onEventRef.current?.(e);
    });
  }, [ctx]);

  const legacyConnect = useCallback(() => {
    if (typeof window === "undefined") return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const engineHttp = resolveEngineHttpUrl(url);
      const engineWs = engineHttp.replace(/^http/, "ws");
      const ws = new WebSocket(`${engineWs}/ws/events`);

      ws.onopen = () => {
        setLegacyConnected(true);
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
          setLegacyLastEvent(flat);
          onEventRef.current?.(flat);
        } catch {
          /* ignore */
        }
      };

      ws.addEventListener("close", () => {
        setLegacyConnected(false);
        if (!reconnectRef.current) return;
        attemptRef.current += 1;
        reconnectTimer.current = setTimeout(
          () => legacyConnect(),
          Math.min(1000 * Math.pow(2, attemptRef.current), 30000)
        );
      });

      wsRef.current = ws;
    } catch (err) {
      console.error("WebSocket connection error:", err);
    }
  }, [url]);

  const legacyDisconnect = useCallback(() => {
    reconnectRef.current = false;
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    if (wsRef.current) wsRef.current.close();
    setLegacyConnected(false);
  }, []);

  useEffect(() => {
    if (ctx) return;
    reconnectRef.current = true;
    legacyConnect();
    return () => {
      legacyDisconnect();
    };
  }, [ctx, legacyConnect, legacyDisconnect]);

  if (ctx) {
    return {
      connect: ctx.connect,
      disconnect: ctx.disconnect,
      lastEvent: ctx.lastEvent,
      isConnected: ctx.isConnected,
    };
  }

  return {
    connect: legacyConnect,
    disconnect: legacyDisconnect,
    lastEvent: legacyLastEvent,
    isConnected: legacyConnected,
  };
}
