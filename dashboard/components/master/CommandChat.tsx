"use client";
import { useCallback } from "react";
import { streamCommand, type CommandEvent } from "@/lib/masterApi";
import { AskJarvis, type AskJarvisSend } from "@/components/AskJarvis";

// Master-product wiring over the shared, canonical <AskJarvis> console. Transport is
// the Master Jarvis SSE stream (/master/command/stream on :8030) — a different backend
// from the trading engine's /jarvis/ask, so only the `send` adapter differs.
export function CommandChat() {
  const send = useCallback<AskJarvisSend>(
    (text, { onText, onTool }) =>
      new Promise<void>((resolve) => {
        streamCommand(
          text,
          (e: CommandEvent) => {
            if (e.type === "tool") onTool?.(e.name);
            if (e.type === "text") onText(e.text);
          },
          resolve,
        );
      }),
    [],
  );

  return (
    <AskJarvis
      send={send}
      title="Command"
      className="mt-8"
      placeholder="Type a command…"
      emptyHint={`Ask Master Jarvis anything — e.g. "how's everything look?"`}
    />
  );
}
