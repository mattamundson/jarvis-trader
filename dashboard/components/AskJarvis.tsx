"use client";

import { useCallback, useState } from "react";
import { Activity } from "lucide-react";

// Canonical, transport-agnostic "Ask Jarvis" chat console.
// Unifies the two former hand-rolled chat UIs (the trading `AskJarvisPanel` and the
// Master-product `CommandChat`) into one multi-turn thread. The transport is injected
// via the `send` prop so each surface keeps its own verified backend:
//   - trading dashboard -> POST /jarvis/ask (fetchJarvisAsk)
//   - master product     -> /master/command/stream (streamCommand, :8030)

export type AskJarvisMeta = {
  sources?: string[];
  actions?: string[];
  intent?: string;
  elapsedMs?: number;
};

export type AskJarvisHandlers = {
  /** Replace the current Jarvis turn's text (call once for a full answer, or repeatedly to stream). */
  onText: (text: string) => void;
  /** Append a tool marker to the current Jarvis turn. */
  onTool?: (name: string) => void;
  /** Attach structured metadata (sources / actions / intent / elapsed) to the current Jarvis turn. */
  onMeta?: (meta: AskJarvisMeta) => void;
};

/** Drives one question end-to-end, emitting text/tool/meta via the handlers. Rejects on error. */
export type AskJarvisSend = (question: string, handlers: AskJarvisHandlers) => Promise<void>;

type Turn = {
  role: "you" | "jarvis";
  text: string;
  tools?: string[];
  meta?: AskJarvisMeta;
  error?: boolean;
};

interface AskJarvisProps {
  send: AskJarvisSend;
  title?: string;
  subtitle?: string;
  placeholder?: string;
  emptyHint?: string;
  className?: string;
}

export function AskJarvis({
  send,
  title = "Ask JARVIS",
  subtitle,
  placeholder = "Ask a question…",
  emptyHint = "Ask JARVIS anything about the market, positions, or pipeline.",
  className,
}: AskJarvisProps) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  const updateLast = useCallback((patch: (t: Turn) => Turn) => {
    setTurns((prev) => {
      if (prev.length === 0) return prev;
      const copy = [...prev];
      copy[copy.length - 1] = patch(copy[copy.length - 1]);
      return copy;
    });
  }, []);

  const handleAsk = useCallback(async () => {
    const q = input.trim();
    if (!q || busy) return;

    setInput("");
    setBusy(true);
    const tools: string[] = [];
    setTurns((prev) => [
      ...prev,
      { role: "you", text: q },
      { role: "jarvis", text: "…", tools },
    ]);

    try {
      await send(q, {
        onText: (text) => updateLast((t) => ({ ...t, text, error: false })),
        onTool: (name) => {
          tools.push(name);
          updateLast((t) => ({ ...t, tools: [...tools] }));
        },
        onMeta: (meta) => updateLast((t) => ({ ...t, meta })),
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      // Graceful handling for a not-yet-live route.
      const friendly =
        msg.includes("404") || msg.includes("Not Found")
          ? "Ask-Jarvis route not yet live — see CLAUDE_CODE_AND_HERMES_INTEGRATION_MAP for wiring instructions."
          : msg;
      updateLast((t) => ({ ...t, text: friendly, error: true }));
    } finally {
      setBusy(false);
    }
  }, [input, busy, send, updateLast]);

  return (
    <div className={`rounded-xl border border-zinc-800 bg-zinc-950/60 ${className ?? ""}`}>
      <div className="border-b border-zinc-800 px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-medium text-zinc-300">
          <Activity className="h-4 w-4" /> {title}
        </div>
        {subtitle && <p className="mt-0.5 text-[11px] text-zinc-500">{subtitle}</p>}
      </div>

      <div className="max-h-80 space-y-3 overflow-y-auto p-4">
        {turns.length === 0 && <p className="text-xs text-zinc-500">{emptyHint}</p>}
        {turns.map((turn, i) => (
          <div key={i} className={turn.role === "you" ? "text-right" : "space-y-1.5"}>
            {turn.tools && turn.tools.length > 0 && (
              <div className="text-[11px] text-amber-400">⚙ {turn.tools.join(" · ")}</div>
            )}
            <span
              className={
                turn.role === "you"
                  ? "inline-block rounded-lg bg-emerald-600/80 px-3 py-1.5 text-xs text-white"
                  : turn.error
                    ? "inline-block rounded-lg border border-rose-800/40 bg-rose-950/30 px-3 py-2 text-[11px] leading-relaxed text-rose-300"
                    : "inline-block rounded-lg bg-zinc-800 px-3 py-2 text-xs leading-relaxed text-zinc-100 whitespace-pre-wrap"
              }
            >
              {turn.text}
            </span>

            {turn.role === "jarvis" && turn.meta && (
              <div className="space-y-1.5 pt-0.5">
                {turn.meta.intent && (
                  <p className="font-mono text-[10px] text-zinc-500">intent: {turn.meta.intent}</p>
                )}
                {turn.meta.sources && turn.meta.sources.length > 0 && (
                  <div className="space-y-1">
                    <p className="text-[10px] uppercase tracking-wider text-zinc-600">Sources</p>
                    {turn.meta.sources.map((src, j) => (
                      <p
                        key={j}
                        className="border-l border-zinc-800 pl-2 font-mono text-[10px] text-zinc-500"
                      >
                        {src}
                      </p>
                    ))}
                  </div>
                )}
                {turn.meta.actions && turn.meta.actions.length > 0 && (
                  <div className="space-y-1">
                    <p className="text-[10px] uppercase tracking-wider text-zinc-600">Actions</p>
                    {turn.meta.actions.map((act, j) => (
                      <p
                        key={j}
                        className="border-l border-emerald-800/40 pl-2 font-mono text-[10px] text-zinc-500"
                      >
                        {act}
                      </p>
                    ))}
                  </div>
                )}
                {typeof turn.meta.elapsedMs === "number" && turn.meta.elapsedMs > 0 && (
                  <p className="text-right font-mono text-[9px] text-zinc-700">
                    {turn.meta.elapsedMs}ms
                  </p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="flex gap-2 border-t border-zinc-800 p-3">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAsk()}
          placeholder={busy ? "JARVIS is working…" : placeholder}
          disabled={busy}
          className="flex-1 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs text-zinc-200 placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-emerald-500/50 disabled:opacity-50"
        />
        <button
          onClick={handleAsk}
          disabled={busy || !input.trim()}
          className="rounded-lg border border-emerald-500/30 bg-emerald-500/15 px-3 py-1.5 text-xs font-semibold text-emerald-400 transition-colors hover:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? "Thinking…" : "Ask"}
        </button>
      </div>
    </div>
  );
}
