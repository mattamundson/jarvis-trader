"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchJarvisAsk, type JarvisAskResponse } from "@/lib/api";

/**
 * Global command palette wired to /jarvis/ask.
 *
 * Cmd+K (mac) / Ctrl+K (win) opens it from any page; Esc closes. Mounted once
 * in app/layout.tsx so it is available on every route. Uses the existing
 * fetchJarvisAsk helper (no bare fetch).
 */
export function JarvisCommandBar() {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<JarvisAskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const close = useCallback(() => {
    setOpen(false);
  }, []);

  // Global Cmd/Ctrl+K to toggle, Esc to close.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // Focus the input when the palette opens.
  useEffect(() => {
    if (open) {
      const id = window.setTimeout(() => inputRef.current?.focus(), 0);
      return () => window.clearTimeout(id);
    }
  }, [open]);

  const handleAsk = useCallback(async () => {
    const q = question.trim();
    if (!q || isLoading) return;

    setIsLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await fetchJarvisAsk(q);
      setResult(res);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes("404") || msg.includes("Not Found")) {
        setError("Ask-Jarvis route not live on the engine yet.");
      } else {
        setError(msg);
      }
    } finally {
      setIsLoading(false);
    }
  }, [question, isLoading]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Ask JARVIS"
      className="fixed inset-0 z-[10000] flex items-start justify-center bg-black/60 p-4 pt-[12vh] backdrop-blur-sm"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="w-full max-w-2xl overflow-hidden rounded-xl border border-cyan-900/50 bg-gray-950 shadow-2xl">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void handleAsk();
          }}
          className="flex items-center gap-3 border-b border-gray-800 px-4 py-3"
        >
          <span className="font-mono text-xs font-bold uppercase tracking-widest text-cyan-400">
            Ask JARVIS
          </span>
          <input
            ref={inputRef}
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask anything — e.g. why did we skip the last MES signal?"
            className="flex-1 bg-transparent text-sm text-gray-100 placeholder:text-gray-600 focus:outline-none"
          />
          <kbd className="rounded border border-gray-700 px-1.5 py-0.5 font-mono text-[10px] text-gray-500">
            Esc
          </kbd>
        </form>

        <div className="max-h-[50vh] overflow-y-auto px-4 py-3">
          {isLoading && (
            <div className="flex items-center gap-2 py-2 text-sm text-gray-400">
              <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-cyan-500 border-t-transparent" />
              Thinking…
            </div>
          )}

          {error && !isLoading && (
            <p className="py-2 text-sm text-red-400">{error}</p>
          )}

          {result && !isLoading && (
            <div className="space-y-3">
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-100">
                {result.answer}
              </p>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-gray-500">
                {result.intent && (
                  <span>
                    <span className="text-gray-600">intent</span> {result.intent}
                  </span>
                )}
                <span>
                  <span className="text-gray-600">took</span> {result.elapsed_ms} ms
                </span>
              </div>
              {result.actions_taken?.length > 0 && (
                <div className="text-xs text-gray-400">
                  <p className="mb-1 text-[10px] uppercase tracking-wider text-gray-600">
                    Actions taken
                  </p>
                  <ul className="space-y-0.5">
                    {result.actions_taken.map((a, i) => (
                      <li key={i}>• {a}</li>
                    ))}
                  </ul>
                </div>
              )}
              {result.sources?.length > 0 && (
                <div className="text-xs text-gray-400">
                  <p className="mb-1 text-[10px] uppercase tracking-wider text-gray-600">
                    Sources
                  </p>
                  <ul className="space-y-0.5">
                    {result.sources.map((s, i) => (
                      <li key={i} className="truncate">
                        • {s}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {!isLoading && !result && !error && (
            <p className="py-2 text-xs text-gray-600">
              Press Enter to ask. Cmd/Ctrl+K toggles this bar from anywhere.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
