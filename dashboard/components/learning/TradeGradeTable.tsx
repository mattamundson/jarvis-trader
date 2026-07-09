"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

const REFRESH_MS = 30_000;

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Types ─────────────────────────────────────────────────────────────────────
// Mirrors the ACTUAL engine response — GET /learning/classify/recent in
// engine/routers/learning_router.py wraps everything as {status, data}. This
// component used to call GET /learning/classify?trade_id=recent, but "recent"
// is not a real trade_id (the endpoint does an exact-match lookup), so that
// call 404'd on every load. /learning/classify/recent is a new batch endpoint
// that classifies the N most recently closed trades. There is no `score`
// (0-100) or `criteria` checklist on the wire — TradeClassifier
// (engine/learning/_experimental/trade_classifier.py) returns setup_quality /
// execution_quality (0.0-1.0 floats) and a flat `factors` string list instead.

type Grade = "A" | "B" | "C" | "D" | "F";

interface TradeGrade {
  trade_id: string;
  symbol: string;
  grade: Grade;
  setup_quality: number;
  execution_quality: number;
  factors: string[];
  explanation: string;
  entry_time: string | null;
  exit_time: string | null;
  pnl: number | null;
}

interface RecentGradesData {
  symbol: string | null;
  count: number;
  grades: TradeGrade[];
}

interface RecentGradesEnvelope {
  status: string;
  data: RecentGradesData;
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

// Factor strings come straight from trade_classifier.py, e.g.
// "excellent_r_multiple_3.20", "quick_execution", "regime_aligned",
// "poor_r_multiple_-0.40", "slow_execution", "regime_misaligned",
// "high_slippage", "loss", "negative_r_multiple". Flag the negative-sounding
// ones so the chip list reads at a glance instead of dumping raw factor codes.
const NEGATIVE_FACTOR_HINTS = ["poor", "slow", "misaligned", "high_slippage", "loss", "negative", "error"];

function isNegativeFactor(factor: string): boolean {
  return NEGATIVE_FACTOR_HINTS.some((hint) => factor.includes(hint));
}

function FactorList({ factors }: { factors: string[] }) {
  if (!factors.length) {
    return (
      <p className="font-mono text-[10px] text-muted-foreground/40 italic">
        No factors recorded
      </p>
    );
  }

  return (
    <div className="flex flex-wrap gap-1">
      {factors.map((f, i) => {
        const negative = isNegativeFactor(f);
        return (
          <span
            key={i}
            className="font-mono text-[9px] rounded px-1.5 py-0.5 border"
            style={{
              color: negative ? "#ff4444" : "#00ff88",
              borderColor: negative ? "#ff444430" : "#00ff8830",
            }}
          >
            {f.replace(/_/g, " ")}
          </span>
        );
      })}
    </div>
  );
}

function QualityBar({ label, value }: { label: string; value: number }) {
  const pct = Math.min(100, Math.max(0, value * 100));
  const color = pct >= 70 ? "#00ff88" : pct >= 40 ? "#ffcc00" : "#ff4444";
  return (
    <div className="space-y-0.5 min-w-[64px]">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground/50">
          {label}
        </span>
        <span className="font-mono text-[9px] tabular-nums" style={{ color }}>
          {pct.toFixed(0)}%
        </span>
      </div>
      <div className="h-1 rounded-full bg-muted overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
    </div>
  );
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

// ── Main component ─────────────────────────────────────────────────────────

export function TradeGradeTable() {
  const { data: envelope, isLoading, error } = useSWR<RecentGradesEnvelope>(
    "/learning/classify/recent?limit=20",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const grades: TradeGrade[] = envelope?.data?.grades ?? [];

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

  if (error) {
    return (
      <div className="rounded-xl border border-border bg-card p-4 space-y-2">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          Trade Grades
        </p>
        <p className="font-mono text-xs text-red-400/70 italic">
          {error instanceof Error ? error.message : "Grade data unavailable — need completed trades with entry/exit data"}
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

  if (!grades.length) {
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
      {grades.length > 1 && <GradeDistribution grades={grades} />}

      {/* Grades table */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            Recent Trade Grades
          </p>
          <span className="font-mono text-[10px] text-muted-foreground">
            {grades.length} trade{grades.length !== 1 ? "s" : ""}
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full font-mono text-xs min-w-[720px]">
            <thead>
              <tr className="border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground">
                <th className="text-left px-4 py-2">Trade</th>
                <th className="text-left px-4 py-2">Symbol</th>
                <th className="text-left px-4 py-2">Entry Time</th>
                <th className="text-center px-4 py-2">Grade</th>
                <th className="text-left px-4 py-2">Quality</th>
                <th className="text-right px-4 py-2">P&L</th>
                <th className="text-left px-4 py-2">Factors</th>
              </tr>
            </thead>
            <tbody>
              {grades.map((row) => (
                <tr
                  key={row.trade_id}
                  className="border-b border-border/40 hover:bg-accent/5 transition-colors align-top"
                >
                  <td className="px-4 py-3 text-muted-foreground text-[10px]">
                    #{String(row.trade_id).slice(-6)}
                  </td>
                  <td className="px-4 py-3" style={{ color: "#00d4ff" }}>
                    {row.symbol || "—"}
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
                  <td className="px-4 py-3 space-y-1.5">
                    <QualityBar label="Setup" value={row.setup_quality} />
                    <QualityBar label="Exec" value={row.execution_quality} />
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
                    <FactorList factors={row.factors ?? []} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
