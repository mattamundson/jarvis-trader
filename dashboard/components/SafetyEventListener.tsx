"use client";

import { useCallback } from "react";
import { mutate } from "swr";
import { useWebSocket } from "@/hooks/useWebSocket";
import type { WsEvent } from "@/hooks/ws-types";
import { useToast } from "@/lib/toast-context";

// SWR keys to revalidate immediately when a safety/P&L event lands, so the HUD
// reflects new state sub-second instead of waiting for the 5s poll.
const SAFETY_KEYS = ["/safety/status", "/health"];
const FILL_KEYS = [
  "/portfolio",
  "/portfolio/paper/positions",
  "/portfolio/history/trades",
  "/safety/status",
];

function revalidate(keys: string[]) {
  for (const k of keys) void mutate(k);
}

/**
 * Pushes engine safety + P&L WebSocket events into the SWR cache so the
 * dashboard reacts in real time. The engine already broadcasts kill_switch,
 * circuit_breaker, safety_event and order_fill over /ws/events
 * (engine/websocket/events.py); this is the read-side wiring only — it never
 * drives any safety decision. Polling remains the fallback when WS is down.
 */
export function SafetyEventListener() {
  const { addToast } = useToast();

  const onEvent = useCallback(
    (event: WsEvent) => {
      switch (event.type) {
        case "kill_switch":
          revalidate(SAFETY_KEYS);
          addToast(
            event.active
              ? "Kill switch ACTIVATED — trading halted"
              : "Kill switch deactivated",
            event.active ? "warning" : "info",
          );
          break;
        case "circuit_breaker":
          revalidate(SAFETY_KEYS);
          addToast(`Circuit breaker: ${event.reason}`, "warning");
          break;
        case "safety_event":
          revalidate(SAFETY_KEYS);
          if (event.message) addToast(`Safety: ${event.message}`, "warning");
          break;
        case "order_fill":
          revalidate(FILL_KEYS);
          break;
        default:
          break;
      }
    },
    [addToast],
  );

  useWebSocket(undefined, onEvent);

  return null;
}
