"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetchEngine, postEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

const REFRESH_MS = 30_000;

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface MemoryLesson {
  id?: string | number;
  type: "lesson" | "pattern" | "warning" | "rule";
  content: string;
  symbol?: string | null;
  created_at?: string | null;
  confidence?: number | null;
  tags?: string[];
}

interface MemoryResponse {
  lessons: MemoryLesson[];
  total?: number;
  error?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function lessonTypeBadgeVariant(type: string): "bull" | "warn" | "bear" | "info" | "neutral" {
  switch (type) {
    case "lesson":  return "info";
    case "pattern": return "bull";
    case "warning": return "warn";
    case "rule":    return "bear";
    default:        return "neutral";
  }
}

function fmtDate(ts: string | null | undefined): string {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleDateString("en-US", {
      month: "short", day: "numeric", year: "numeric",
    });
  } catch {
    return ts;
  }
}

// ── Add lesson form ───────────────────────────────────────────────────────────

function AddLessonForm({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState("");
  const [type, setType] = useState<MemoryLesson["type"]>("lesson");
  const [symbol, setSymbol] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!content.trim()) return;
    setSaving(true);
    setSaveError(null);
    try {
      await postEngine("/learning/memory", {
        type,
        content: content.trim(),
        symbol: symbol.trim() || null,
      });
      setContent("");
      setSymbol("");
      setType("lesson");
      setOpen(false);
      onAdded();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save lesson");
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="font-mono text-[11px] text-accent/80 hover:text-accent border border-accent/20 hover:border-accent/40 rounded-lg px-3 py-1.5 transition-colors"
      >
        + Add Lesson
      </button>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-xl border border-accent/20 bg-card p-4 space-y-3">
      <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
        Record a Lesson
      </p>

      <div className="flex gap-2">
        {(["lesson", "pattern", "warning", "rule"] as MemoryLesson["type"][]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setType(t)}
            className={`font-mono text-[10px] rounded px-2 py-1 border transition-colors ${
              type === t
                ? "border-accent/40 bg-accent/10 text-accent"
                : "border-border text-muted-foreground hover:text-foreground"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder="Describe the lesson, pattern, or rule…"
        rows={3}
        className="w-full font-mono text-xs bg-background border border-border rounded-lg p-3 text-foreground placeholder:text-muted-foreground/40 resize-none focus:outline-none focus:border-accent/50"
        required
      />

      <input
        value={symbol}
        onChange={(e) => setSymbol(e.target.value.toUpperCase())}
        placeholder="Symbol (optional, e.g. MES)"
        className="w-full font-mono text-xs bg-background border border-border rounded-lg px-3 py-2 text-foreground placeholder:text-muted-foreground/40 focus:outline-none focus:border-accent/50"
      />

      {saveError && (
        <p className="font-mono text-[11px] text-red-400/80">{saveError}</p>
      )}

      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={saving || !content.trim()}
          className="font-mono text-[11px] bg-accent/10 hover:bg-accent/20 border border-accent/30 text-accent rounded-lg px-4 py-1.5 transition-colors disabled:opacity-40"
        >
          {saving ? "Saving…" : "Save Lesson"}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="font-mono text-[11px] text-muted-foreground hover:text-foreground transition-colors"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

// ── Main component ─────────────────────────────────────────────────────────

export function MemoryPanel() {
  const { data, isLoading, error, mutate } = useSWR<MemoryResponse>(
    "/learning/memory",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const lessons = data?.lessons ?? [];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="rounded-xl border border-border bg-card p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Learning Memory
            </p>
            <p className="font-mono text-[10px] text-muted-foreground/40 mt-0.5">
              Accumulated lessons, patterns, warnings and rules
            </p>
          </div>
          {!isLoading && !error && (
            <span className="font-mono text-[10px] text-muted-foreground">
              {data?.total ?? lessons.length} entries
            </span>
          )}
        </div>

        <AddLessonForm onAdded={() => mutate()} />
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="font-mono text-xs text-muted-foreground/50 animate-pulse">
            Loading memory…
          </p>
        </div>
      ) : error || data?.error ? (
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="font-mono text-xs text-red-400/70 italic">
            {data?.error ?? "Memory unavailable — learning system may not be initialized"}
          </p>
        </div>
      ) : lessons.length === 0 ? (
        <div className="rounded-xl border border-border bg-card p-6 text-center">
          <p className="font-mono text-xs text-muted-foreground/50 italic">
            No lessons recorded yet. Add your first lesson above or let the
            learning system discover patterns automatically.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {lessons.map((lesson, i) => (
            <div
              key={lesson.id ?? i}
              className="rounded-xl border border-border bg-card p-4 space-y-2 hover:border-border/80 transition-colors"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge variant={lessonTypeBadgeVariant(lesson.type)}>
                    {lesson.type}
                  </Badge>
                  {lesson.symbol && (
                    <Badge variant="neutral">{lesson.symbol}</Badge>
                  )}
                  {lesson.tags?.map((tag) => (
                    <span
                      key={tag}
                      className="font-mono text-[9px] text-muted-foreground/50 border border-border/40 rounded px-1.5 py-0.5"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
                {lesson.created_at && (
                  <span className="font-mono text-[10px] text-muted-foreground/40 whitespace-nowrap shrink-0">
                    {fmtDate(lesson.created_at)}
                  </span>
                )}
              </div>

              <p className="font-mono text-[11px] text-foreground/80 leading-relaxed">
                {lesson.content}
              </p>

              {lesson.confidence != null && (
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[10px] text-muted-foreground/40 uppercase tracking-wider">
                    Confidence
                  </span>
                  <div className="flex-1 max-w-[80px] h-1 rounded-full bg-muted overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${Math.min(100, lesson.confidence * 100)}%`,
                        backgroundColor:
                          lesson.confidence >= 0.7 ? "#00ff88"
                          : lesson.confidence >= 0.4 ? "#ffcc00"
                          : "#888",
                      }}
                    />
                  </div>
                  <span className="font-mono text-[10px] text-muted-foreground/40 tabular-nums">
                    {(lesson.confidence * 100).toFixed(0)}%
                  </span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
