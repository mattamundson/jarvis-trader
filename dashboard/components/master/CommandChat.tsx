"use client";
import { useState } from "react";
import { streamCommand, type CommandEvent } from "@/lib/masterApi";

type Msg = { role: "you" | "jarvis"; text: string; tools?: string[] };

export function CommandChat() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setMsgs((m) => [...m, { role: "you", text }]);
    setBusy(true);
    const tools: string[] = [];
    setMsgs((m) => [...m, { role: "jarvis", text: "…", tools }]);
    streamCommand(
      text,
      (e: CommandEvent) => {
        if (e.type === "tool") tools.push(e.name);
        if (e.type === "text") {
          setMsgs((m) => {
            const copy = [...m];
            copy[copy.length - 1] = { role: "jarvis", text: e.text, tools: [...tools] };
            return copy;
          });
        }
      },
      () => setBusy(false),
    );
  }

  return (
    <div className="mt-8 rounded-xl border border-zinc-700 bg-zinc-900">
      <div className="border-b border-zinc-700 px-4 py-2 text-sm font-semibold text-zinc-300">
        Command
      </div>
      <div className="max-h-80 space-y-3 overflow-y-auto p-4">
        {msgs.length === 0 && (
          <p className="text-sm text-zinc-500">
            Ask Master Jarvis anything — e.g. &quot;how&apos;s everything look?&quot;
          </p>
        )}
        {msgs.map((mm, i) => (
          <div key={i} className={mm.role === "you" ? "text-right" : ""}>
            {mm.tools && mm.tools.length > 0 && (
              <div className="mb-1 text-xs text-amber-400">⚙ {mm.tools.join(" · ")}</div>
            )}
            <span
              className={
                mm.role === "you"
                  ? "inline-block rounded-lg bg-blue-600 px-3 py-2 text-sm text-white"
                  : "inline-block rounded-lg bg-zinc-800 px-3 py-2 text-sm text-zinc-100 whitespace-pre-wrap"
              }
            >
              {mm.text}
            </span>
          </div>
        ))}
      </div>
      <div className="flex gap-2 border-t border-zinc-700 p-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder={busy ? "Jarvis is working…" : "Type a command…"}
          disabled={busy}
          className="flex-1 rounded-lg bg-zinc-800 px-3 py-2 text-sm text-zinc-100 outline-none"
        />
        <button
          onClick={send}
          disabled={busy}
          className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          Send
        </button>
      </div>
    </div>
  );
}
