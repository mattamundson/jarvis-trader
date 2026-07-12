"use client";
import { useMemo } from "react";
import { streamCommand } from "@/lib/masterApi";
import { AskJarvis, type AskJarvisSend } from "@/components/AskJarvis";
import { createCommandChatSend } from "@/lib/ask-jarvis-adapters";

// Master-product wiring over the shared, canonical <AskJarvis> console. Transport is
// the Master Jarvis SSE stream (/master/command/stream on :8030) — a different backend
// from the trading engine's /jarvis/ask, so only the `send` adapter differs. Adapter
// factory lives in lib/ask-jarvis-adapters.ts (P5.1) so its event-routing contract can
// be unit-tested outside this JSX file.
export function CommandChat() {
  const send = useMemo<AskJarvisSend>(() => createCommandChatSend(streamCommand), []);

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
