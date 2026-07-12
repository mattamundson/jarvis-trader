/**
 * P5.1 — real unit tests for the two <AskJarvis> "send" adapter contracts (P4.3).
 *
 * `createTradingAskSend` and `createCommandChatSend` (lib/ask-jarvis-adapters.ts)
 * are the only piece of AskJarvis's transport-agnostic design that has real logic
 * (JarvisAskResponse -> AskJarvisMeta field mapping; CommandEvent -> onText/onTool
 * routing) — the two former call sites (app/command-center/page.tsx,
 * components/master/CommandChat.tsx) can't be loaded by Node's native
 * TS-stripping test runner since they're JSX. Same convention as
 * tests/position-sizing.test.ts / tests/command-center-helpers.test.ts: real
 * executed node:test, transports dependency-injected so no network is touched.
 *
 * Run via: node --test tests/ask-jarvis-adapters.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  createTradingAskSend,
  createCommandChatSend,
} from "../lib/ask-jarvis-adapters.ts";
import type { AskJarvisMeta } from "../components/AskJarvis.tsx";
import type { JarvisAskResponse } from "../lib/api.ts";
import type { CommandEvent } from "../lib/masterApi.ts";

function captureHandlers() {
  const texts: string[] = [];
  const tools: string[] = [];
  const metas: AskJarvisMeta[] = [];
  return {
    texts,
    tools,
    metas,
    handlers: {
      onText: (text: string) => texts.push(text),
      onTool: (name: string) => tools.push(name),
      onMeta: (meta: AskJarvisMeta) => metas.push(meta),
    },
  };
}

test("createTradingAskSend maps JarvisAskResponse fields onto AskJarvisMeta", async () => {
  const response: JarvisAskResponse = {
    answer: "MES is trending up on strong volume.",
    sources: ["discord:#market-updates", "pipeline:MES"],
    actions_taken: ["fetched_bars"],
    elapsed_ms: 842,
    intent: "market_status",
  };
  const send = createTradingAskSend(async () => response);
  const { texts, metas, handlers } = captureHandlers();

  await send("what is MES doing?", handlers);

  assert.deepEqual(texts, [response.answer]);
  assert.deepEqual(metas, [
    {
      sources: response.sources,
      actions: response.actions_taken,
      intent: response.intent,
      elapsedMs: response.elapsed_ms,
    },
  ]);
});

test("createTradingAskSend rejects when the injected fetch rejects (no swallowed errors)", async () => {
  const send = createTradingAskSend(async () => {
    throw new Error("404 Not Found");
  });
  const { handlers } = captureHandlers();

  await assert.rejects(() => send("anything", handlers), /404/);
});

test("createCommandChatSend routes tool events to onTool and text events to onText, in order", async () => {
  const events: CommandEvent[] = [
    { type: "tool", name: "get_positions" },
    { type: "text", text: "Checking positions…" },
    { type: "text", text: "You have 1 open MES position." },
    { type: "done" },
  ];
  const stream = (
    _text: string,
    onEvent: (e: CommandEvent) => void,
    onClose: () => void,
  ) => {
    for (const e of events) onEvent(e);
    onClose();
    return () => {};
  };
  const send = createCommandChatSend(stream);
  const { texts, tools, handlers } = captureHandlers();

  await send("how's everything look?", handlers);

  assert.deepEqual(tools, ["get_positions"]);
  assert.deepEqual(texts, ["Checking positions…", "You have 1 open MES position."]);
});

test("createCommandChatSend resolves once the stream calls onClose, even with zero events", async () => {
  const stream = (
    _text: string,
    _onEvent: (e: CommandEvent) => void,
    onClose: () => void,
  ) => {
    onClose();
    return () => {};
  };
  const send = createCommandChatSend(stream);
  const { texts, tools, handlers } = captureHandlers();

  await send("noop", handlers);

  assert.deepEqual(texts, []);
  assert.deepEqual(tools, []);
});
