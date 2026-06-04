"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Search, Loader2, CornerDownLeft, X } from "lucide-react";
import { fetchJarvisAsk, type JarvisAskResponse } from "@/lib/api";

/**
 * Global Cmd/Ctrl+K command palette that talks to the existing /jarvis/ask
 * endpoint (via fetchJarvisAsk). Mounted once in the root layout so it is
 * reachable from every page. Additive — does not modify any existing surface.
 */
export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<JarvisAskResponse | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Global Cmd/Ctrl+K toggles the palette; Esc closes it.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Focus the input when the palette opens (next tick so it is mounted).
  useEffect(() => {
    if (!open) return;
    const id = setTimeout(() => inputRef.current?.focus(), 0);
    return () => clearTimeout(id);
  }, [open]);

  const ask = useCallback(async () => {
    const q = question.trim();
    if (!q || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await fetchJarvisAsk(q));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Jarvis is unreachable.");
    } finally {
      setLoading(false);
    }
  }, [question, loading]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center bg-black/60 p-4 pt-[12vh]"
      role="dialog"
      aria-modal="true"
      aria-label="Ask Jarvis command palette"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) setOpen(false);
      }}
    >
      <div className="w-full max-w-2xl overflow-hidden rounded-xl border border-border bg-card shadow-2xl">
        {/* Input row */}
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <Search className="h-4 w-4 text-muted-foreground" />
          <input
            ref={inputRef}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") ask();
            }}
            placeholder="Ask Jarvis anything…  (e.g. why did we skip the last MES signal?)"
            className="flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
          />
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin text-accent" />
          ) : (
            <kbd className="hidden items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground sm:flex">
              <CornerDownLeft className="h-3 w-3" /> Enter
            </kbd>
          )}
          <button
            aria-label="Close command palette"
            onClick={() => setOpen(false)}
            className="text-muted-foreground transition-colors hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Result area */}
        <div className="max-h-[50vh] overflow-y-auto px-4 py-3 text-sm">
          {error && <p className="text-bear">{error}</p>}
          {!error && !result && !loading && (
            <p className="text-muted-foreground">
              Press <span className="font-mono">Cmd/Ctrl+K</span> anywhere to open · Enter
              to ask · Esc to close.
            </p>
          )}
          {loading && <p className="text-muted-foreground">Thinking…</p>}
          {result && (
            <div className="space-y-3">
              <p className="whitespace-pre-wrap text-foreground">{result.answer}</p>
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                {result.intent && (
                  <span className="rounded border border-border px-1.5 py-0.5 font-mono">
                    intent: {result.intent}
                  </span>
                )}
                <span>{result.elapsed_ms} ms</span>
              </div>
              {result.actions_taken?.length > 0 && (
                <p className="text-[11px] text-muted-foreground">
                  actions: {result.actions_taken.join(", ")}
                </p>
              )}
              {result.sources?.length > 0 && (
                <p className="text-[11px] text-muted-foreground">
                  sources: {result.sources.join(", ")}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
