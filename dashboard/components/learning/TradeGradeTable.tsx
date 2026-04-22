"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

const REFRESH_MS = 30_000;

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Types ─────────────────────────────────────────────────────────────────────

type Grade = "A" | "B" | "C" | "D" | "F";

interface GradeCriteria {
  name: string;
  met: boolean;
  value?: string | number | null;
  threshold?: string | number | null;
}

interface TradeGrade {
  trade_id: string | number;
  symbol?: string;
  grade: Grade;
  score: number;
  criteria: GradeCriteria[];
  entry_time?: string | null;
  pnl?: number | null;
  notes?: string | null;
  error?: string;
}

interface ClassifyResponse {
  trade_id: string | number;
  grade: Grade;
  score: number;
  symbol?: string;
  criteria: GradeCriteria[];
  entry_time?: string | null;
  pnl?: number | null;
  notes?: string | null;
  recent_grades?: TradeGrade[];
  error?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function gradeColor(grade: Grade): string {
  switch (grade) {
    case "A": return "#00ff88";
    case "B": return "#00d4ff";
    case "C": return "#ffcc00";
    case "D": return "#ff9500";
    case "F": return "#ff4444";
    default:  return "#888";
  }
}

function gradeBadgeVariant(grade: Grade): "bull" | "info" | "warn" | "bear" | "neutral" {
  switch (grade) {
    case "A": return "bull";
    case "B": return "info";
    case "C": return "warn";
    case "D": return "bear";
    case "F": return "bear";
    default:  return "neutral";
  }
}

function gradeDescription(grade: Grade): string {
  switch (grade) {
    case "A": return "Excellent — all criteria met";
    case "B": return "Good — most criteria met";
    case "C": return "Average — mixed execution";
    case "D": return "Poor — several criteria missed";
    case "F": return "Failed — avoid this setup";
    default:  return "Unknown";
  }
}

function fmtTime(ts: string | null | undefined): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

// ── Grade distribution bar ─────────────────────────────────────────────────

function GradeDistribution({ grades }: { grades: TradeGrade[] }) {
  const counts: Record<Grade, number> = { A: 0, B: 0, C: 0, D: 0, F: 0 };
  for (const g of grades) {
    if (g.grade in counts) counts[g.grade]++;
  }
  const total = grades.length || 1;

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
        Grade Distribution — Last {grades.length} Trades
      </p>
      <div className="flex items-end gap-1 h-10">
        {(["A", "B", "C", "D", "F"] as Grade[]).map((g) => {
          const pct = (counts[g] / total) * 100;
          return (
            <div key={g} className="flex-1 flex flex-col items-center gap-1">
              <span className="font-mono text-[9px] tabular-nums" style={{ color: gradeColor(g) }}>
                {counts[g]}
              </span>
              <div
                className="w-full rounded-t transition-all"
                style={{
                  height: `${Math.max(2, pct * 0.32)}rem`,
                  backgroundColor: gradeColor(g),
                  opacity: 0.8,
                }}
              />
            </div>
          );
        })}
      </div>
      <div className="flex gap-1">
        {(["A", "B", "C", "D", "F"] as Grade[]).map((g) => (
          <div key={g} className="flex-1 text-center">
            <span
              className="font-mono text-[10px] font-bold"
              style={{ color: gradeColor(g) }}
            >
              {g}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Criteria checklist ─────────────────────────────────────────────────────

function CriteriaList({ criteria }: { criteria: GradeCriteria[] }) {
  if (!criteria?.length) {
    return (
      <p className="font-mono text-[10px] text-muted-foreground/40 italic">
        No criteria data
      </p>
    );
  }

  return (
    <div className="space-y-1">
      {criteria.map((c, i) => (
        <div key={i} className="flex items-center gap-2 font-mono text-[11px]">
          <span style={{ color: c.met ? "#00ff88" : "#ff4444" }}>
            {c.met ? "✓" : "✗"}
          </span>
          <span className={c.met ? "text-foreground/80" : "text-muted-foreground/60"}>
            {c.name}
          </span>
          {(c.value != null || c.threshold != null) && (
            <span className="text-muted-foreground/40 text-[10px]">
              {c.value != null ? String(c.value) : ""}
              {c.threshold != null ? ` / ${c.threshold}` : ""}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────

export function TradeGradeTable() {
  const { data, isLoading, error } = useSWR<ClassifyResponse>(
    "/learning/classify?trade_id=recent",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const recentGrades: TradeGrade[] = data?.recent_grades ?? [];

  // If the endpoint returns a single grade with no recent list, treat it as one entry
  const displayGrades: TradeGrade[] =
    recentGrades.length > 0
      ? recentGrades
      : data && !data.error
      ? [
          {
            trade_id: data.trade_id,
            symbol: data.symbol,
            grade: data.grade,
            score: data.score,
            criteria: data.criteria ?? [],
            entry_time: data.entry_time,
            pnl: data.pnl,
            notes: data.notes,
          },
        ]
      : [];

  if (isLoading) {
    return (
      <div className="rounded-xl border border-border bg-card p-4">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-3">
          Trade Grades
        </p>
        <p className="font-mono text-xs text-muted-foreground/50 animate-pulse">
          Loading trade grades…
        </p>
      </div>
    );
  }

  if (error || data?.error) {
    return (
      <div className="rounded-xl border border-border bg-card p-4 space-y-2">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          Trade Grades
        </p>
        <p className="font-mono text-xs text-red-400/70 italic">
          {data?.error ?? "Grade data unavailable — need completed trades with entry/exit data"}
        </p>
        <div className="mt-3 rounded-lg border border-border/50 bg-muted/10 p-3 space-y-1.5">
          <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            Grade Scale Reference
          </p>
          {(["A", "B", "C", "D", "F"] as Grade[]).map((g) => (
            <div key={g} className="flex items-center gap-2 font-mono text-[11px]">
              <span className="font-bold" style={{ color: gradeColor(g) }}>{g}</span>
              <span className="text-muted-foreground/60">{gradeDescription(g)}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (!displayGrades.length) {
    return (
      <div className="rounded-xl border border-border bg-card p-6 text-center">
        <p className="font-mono text-xs text-muted-foreground/50 italic">
          No graded trades yet. Grades appear after trades close.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Distribution chart */}
      {displayGrades.length > 1 && <GradeDistribution grades={displayGrades} />}

      {/* Grades table */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            Recent Trade Grades
          </p>
          <span className="font-mono text-[10px] text-muted-foreground">
            {displayGrades.length} trade{displayGrades.length !== 1 ? "s" : ""}
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full font-mono text-xs min-w-[600px]">
            <thead>
              <tr className="border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground">
                <th className="text-left px-4 py-2">Trade</th>
                <th className="text-left px-4 py-2">Symbol</th>
                <th className="text-left px-4 py-2">Entry Time</th>
                <th className="text-center px-4 py-2">Grade</th>
                <th className="text-right px-4 py-2">Score</th>
                <th className="text-right px-4 py-2">P&L</th>
                <th className="text-left px-4 py-2">Criteria</th>
              </tr>
            </thead>
            <tbody>
              {displayGrades.map((row, i) => {
                const metCount = (row.criteria ?? []).filter((c) => c.met).length;
                const totalCriteria = (row.criteria ?? []).length;
                return (
                  <tr
                    key={String(row.trade_id) + i}
                    className="border-b border-border/40 hover:bg-accent/5 transition-colors align-top"
                  >
                    <td className="px-4 py-3 text-muted-foreground text-[10px]">
                      #{String(row.trade_id).slice(-6)}
                    </td>
                    <td className="px-4 py-3" style={{ color: "#00d4ff" }}>
                      {row.symbol ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-[10px] text-muted-foreground whitespace-nowrap">
                      {fmtTime(row.entry_time)}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <div className="flex flex-col items-center gap-1">
                        <span
                          className="font-mono text-lg font-bold"
                          style={{ color: gradeColor(row.grade) }}
                        >
                          {row.grade}
                        </span>
                        <Badge variant={gradeBadgeVariant(row.grade)}>
                          {gradeDescription(row.grade).split(" — ")[0]}
                        </Badge>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      <span style={{ color: row.score >= 70 ? "#00ff88" : row.score >= 50 ? "#ffcc00" : "#ff4444" }}>
                        {row.score.toFixed(0)}
                      </span>
                      <span className="text-muted-foreground/40">/100</span>
                    </td>
                    <td
                      className="px-4 py-3 text-right tabular-nums font-semibold"
                      style={{ color: row.pnl == null ? "#888" : row.pnl >= 0 ? "#00ff88" : "#ff4444" }}
                    >
                      {row.pnl != null
                        ? `${row.pnl >= 0 ? "+" : ""}$${row.pnl.toFixed(2)}`
                        : "—"}
                    </td>
                    <td className="px-4 py-3 max-w-[220px]">
                      <div className="text-[10px] text-muted-foreground mb-1">
                        {metCount}/{totalCriteria} met
                      </div>
                      <CriteriaList criteria={row.criteria ?? []} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
