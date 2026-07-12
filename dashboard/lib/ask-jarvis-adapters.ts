// Pure, testable factories for the two <AskJarvis> "send" adapters (P4.3).
// Extracted from app/command-center/page.tsx and components/master/CommandChat.tsx
// (both JSX, unloadable by Node's native TS-stripping test runner) so the adapter
// contracts — trading /jarvis/ask response mapping vs master SSE event routing —
// can be exercised with real executed tests. Byte-identical logic, no behavior change.
// Both transports are dependency-injected so tests never touch the network.

import type { AskJarvisSend } from "@/components/AskJarvis";
import type { JarvisAskResponse } from "./api";
import type { CommandEvent } from "./masterApi";

/** Trading dashboard adapter: POST /jarvis/ask (fetchJarvisAsk) — single-shot answer + meta. */
export function createTradingAskSend(
  fetchAsk: (question: string) => Promise<JarvisAskResponse>,
): AskJarvisSend {
  return async (question, { onText, onMeta }) => {
    const res = await fetchAsk(question);
    onText(res.answer);
    onMeta?.({
      sources: res.sources,
      actions: res.actions_taken,
      intent: res.intent,
      elapsedMs: res.elapsed_ms,
    });
  };
}

/** Master-product adapter: /master/command/stream SSE (streamCommand) — tool/text event routing. */
export function createCommandChatSend(
  stream: (
    text: string,
    onEvent: (e: CommandEvent) => void,
    onClose: () => void,
  ) => () => void,
): AskJarvisSend {
  return (text, { onText, onTool }) =>
    new Promise<void>((resolve) => {
      stream(
        text,
        (e) => {
          if (e.type === "tool") onTool?.(e.name);
          if (e.type === "text") onText(e.text);
        },
        resolve,
      );
    });
}
