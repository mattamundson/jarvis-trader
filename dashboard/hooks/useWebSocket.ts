"use client";

import { useContext, useEffect, useRef } from "react";
import { EngineWebSocketContext } from "@/lib/engine-websocket-context";
import type { WsEvent } from "./ws-types";

export type { WsEvent } from "./ws-types";

type WsEventHandler = (event: WsEvent) => void;

/**
 * Subscribe to the shared engine WebSocket singleton (`EngineWebSocketProvider`,
 * mounted once in `app/layout.tsx`). All connection/reconnect/parsing logic
 * lives in `lib/engine-websocket-context.tsx` — this hook is a thin accessor
 * so call sites don't need to import the context directly.
 *
 * The `url` param is accepted for backward compatibility with existing call
 * sites but is unused: the provider is always mounted above every page, so
 * there is exactly one connection for the whole app.
 */
export function useWebSocket(_url?: string, onEvent?: WsEventHandler) {
  const ctx = useContext(EngineWebSocketContext);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    if (!ctx) return;
    return ctx.subscribe((e) => {
      onEventRef.current?.(e);
    });
  }, [ctx]);

  if (ctx) {
    return {
      connect: ctx.connect,
      disconnect: ctx.disconnect,
      lastEvent: ctx.lastEvent,
      isConnected: ctx.isConnected,
    };
  }

  return {
    connect: () => {},
    disconnect: () => {},
    lastEvent: null as WsEvent | null,
    isConnected: false,
  };
}
