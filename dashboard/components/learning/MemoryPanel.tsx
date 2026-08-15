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
// Mirrors the ACTUAL engine contract — engine/routers/learning_router.py:
//   GET  /learning/memory  -> {status, data: {filter_condition, total, lessons}}
//   POST /learning/memory  -> body must be LessonRequest {lesson, category}
// `lessons` entries are `asdict(Lesson)` from
// engine/learning/_experimental/session_memory.py: {date, condition,
// lesson_text, trades_affected, outcome}. There is no id/type/symbol/
// confidence/tags field on the wire. The POST body used to send
// {type, content, symbol}, which does not match LessonRequest and 422'd on
// every submit — fixed below by sending {lesson, category}.

interface MemoryLesson {
  date: string;
  condition: string;
  lesson_text: string;
  trades_affected: string[];
  outcome: "positive" | "neutral" | "negative" | string;
}

interface MemoryData {
  filter_condition: string | null;
  total: number;
  lessons: MemoryLesson[];
}

interface MemoryEnvelope {
  status: string;
  data: MemoryData;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function outcomeBadgeVariant(outcome: string): "bull" | "bear" | "neutral" {
  if (outcome === "positive") return "bull";
  if (outcome === "negative") return "bear";
  return "neutral";
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

// The GET /learning/memory `condition` filter examples in learning_router.py
// are market-regime strings (e.g. TRENDING, CHOPPY) — this list mirrors that
// so a saved lesson can actually be found again by the existing filter param.
const CONDITIONS = ["general", "TRENDING", "CHOPPY", "RANGE"] as const;

// ── Add lesson form ───────────────────────────────────────────────────────────

function AddLessonForm({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState("");
  const [category, setCategory] = useState<string>("general");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!content.trim()) return;
    setSaving(true);
    setSaveError(null);
    try {
      // LessonRequest (engine/routers/learning_router.py) requires
      // {lesson: str, category: str} — sending {type, content, symbol} (the
      // old shape) 422'd every time.
      await postEngine("/learning/memory", {
        lesson: content.trim(),
        category,
      });
      setContent("");
      setCategory("general");
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
        {CONDITIONS.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setCategory(c)}
            className={`font-mono text-[10px] rounded px-2 py-1 border transition-colors ${
              category === c
                ? "border-accent/40 bg-accent/10 text-accent"
                : "border-border text-muted-foreground hover:text-foreground"
            }`}
          >
            {c}
          </button>
        ))}
      </div>

      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder="Describe the lesson learned…"
        rows={3}
        className="w-full font-mono text-xs bg-background border border-border rounded-lg p-3 text-foreground placeholder:text-muted-foreground/40 resize-none focus:outline-none focus:border-accent/50"
        required
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
  const { data: envelope, isLoading, error, mutate } = useSWR<MemoryEnvelope>(
    "/learning/memory",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const memData = envelope?.data;
  const lessons = memData?.lessons ?? [];

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
              Accumulated lessons, keyed by market condition
            </p>
          </div>
          {!isLoading && !error && (
            <span className="font-mono text-[10px] text-muted-foreground">
              {memData?.total ?? lessons.length} entries
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
      ) : error ? (
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="font-mono text-xs text-red-400/70 italic">
            {error instanceof Error ? error.message : "Memory unavailable — learning system may not be initialized"}
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
              key={i}
              className="rounded-xl border border-border bg-card p-4 space-y-2 hover:border-border/80 transition-colors"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge variant="neutral">{lesson.condition}</Badge>
                  <Badge variant={outcomeBadgeVariant(lesson.outcome)}>{lesson.outcome}</Badge>
                  {lesson.trades_affected?.length > 0 && (
                    <span className="font-mono text-[9px] text-muted-foreground/50 border border-border/40 rounded px-1.5 py-0.5">
                      {lesson.trades_affected.length} trade{lesson.trades_affected.length !== 1 ? "s" : ""}
                    </span>
                  )}
                </div>
                {lesson.date && (
                  <span className="font-mono text-[10px] text-muted-foreground/40 whitespace-nowrap shrink-0">
                    {fmtDate(lesson.date)}
                  </span>
                )}
              </div>

              <p className="font-mono text-[11px] text-foreground/80 leading-relaxed">
                {lesson.lesson_text}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
