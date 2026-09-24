"use client";

import { useEffect, useRef } from "react";

// ── Event type definitions ─────────────────────────────────────────────────

export interface HelloEvent {
  type: "hello";
  ts: string;
  subscribed_topics: string[];
}

export interface PingEvent {
  type: "ping";
  ts: string;
}

export interface VerdictPayload {
  final_action: string;
  final_quantity: number;
  requires_human: boolean;
  confidence: number;
  regime: string;
  elapsed_seconds: number;
}

export interface VerdictEvent {
  type: "verdict";
  symbol: string;
  verdict: VerdictPayload;
  ts: string;
}

export interface AnalystSignalsEvent {
  type: "analyst_signals";
  symbol: string;
  reports: Record<string, unknown>;
  ts: string;
}

export type PipelineWsEvent =
  | HelloEvent
  | PingEvent
  | VerdictEvent
  | AnalystSignalsEvent;

// ── URL resolution ────────────────────────────────────────────────────────
//
// SECURITY (2026-08-17): client-side WS now ALWAYS connects same-origin so
// the Next.js rewrite in next.config.ts injects the server-only ENGINE_API_KEY
// (see /ws/pipeline rewrite). We removed the NEXT_PUBLIC_ENGINE_URL direct-
// connect path and the NEXT_PUBLIC_ENGINE_API_KEY fallback: shipping the engine
// key to the browser was an active secret-leak vector (any visitor could
// extract it from the bundle). Deploy targets that need direct-connect must
// configure the rewrite server-side instead of exposing the key client-side.

function resolveWsUrl(): string {
  // Same-origin only — the Next.js proxy rewrite handles the WS upgrade and
  // injects the server-only ENGINE_API_KEY.
  if (typeof window === "undefined") return "";
  return window.location.origin;
}

// /ws/pipeline requires api_key auth (browsers can't send custom headers on a
// WS upgrade — see engine/routers/pipeline_ws_router.py). With same-origin
// resolution the Next.js rewrite (next.config.ts) injects the server-only key,
// so the client must NOT append one. Direct-connect deployments must use the
// rewrite, not a client key.
function resolveApiKey(): string {
  return "";
}

// ── usePipelineSocket hook ─────────────────────────────────────────────────

/**
 * Opens /ws/pipeline on the engine and calls `onEvent` for each message.
 * Reconnects with exponential backoff (max 30 s) on unexpected close.
 * Gracefully degrades — if the WS URL cannot be resolved the hook is a no-op.
 */
export function usePipelineSocket(
  onEvent: (event: PipelineWsEvent) => void
): void {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef(true);
  const attemptRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    reconnectRef.current = true;

    function connect() {
      if (typeof window === "undefined") return;
      if (wsRef.current?.readyState === WebSocket.OPEN) return;

      const base = resolveWsUrl();
      if (!base) return;

      const key = resolveApiKey();
      const url = key
        ? `${base}/ws/pipeline?api_key=${encodeURIComponent(key)}`
        : `${base}/ws/pipeline`;

      try {
        const ws = new WebSocket(url);

        ws.onopen = () => {
          attemptRef.current = 0;
        };

        ws.onmessage = (ev) => {
          try {
            const parsed = JSON.parse(ev.data as string) as PipelineWsEvent;
            // Suppress ping frames — they are keep-alive only
            if (parsed.type === "ping") return;
            onEventRef.current(parsed);
          } catch {
            // Ignore unparseable frames
          }
        };

        ws.onclose = () => {
          wsRef.current = null;
          if (!reconnectRef.current) return;
          attemptRef.current += 1;
          const delay = Math.min(
            1000 * Math.pow(2, attemptRef.current - 1),
            30_000
          );
          timerRef.current = setTimeout(connect, delay);
        };

        ws.onerror = () => {
          // onclose fires after onerror — reconnect handled there
        };

        wsRef.current = ws;
      } catch {
        // WebSocket constructor can throw in restricted environments
      }
    }

    connect();

    return () => {
      reconnectRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, []); // no deps — intentionally stable across re-renders
}
