/**
 * Jarvis-Trader Pipeline Adapter — cli/format-event.ts
 * Formats pipeline events for terminal output in Paperclip CLI.
 */

import type { AdapterEvent } from "@paperclipai/sdk";

export function formatEvent(event: AdapterEvent): string {
  const ts = new Date().toISOString().slice(11, 19);
  const { status, message, metadata } = event;

  const statusIcon: Record<string, string> = {
    running:   "⚡",
    completed: "✅",
    failed:    "❌",
    waiting:   "⏳",
  };

  const icon = statusIcon[status] ?? "•";
  let line = `[${ts}] ${icon} ${message}`;

  if (metadata?.token_usage) {
    const total = metadata.total_tokens ?? 0;
    line += `\n         Tokens: ${total} | Decision: ${metadata.decision ?? "—"} | Confidence: ${metadata.confidence ?? "—"}`;
  }

  return line;
}
