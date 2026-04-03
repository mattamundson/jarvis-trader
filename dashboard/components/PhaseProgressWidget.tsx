"use client";

import React, { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CheckCircle2, ArrowRight, Circle, Target } from "lucide-react";
import { fetchEngine } from "@/lib/api";


// ── Types ─────────────────────────────────────────────────────────────────────

interface PerformanceMetrics {
  profit_factor: number;
  sharpe_ratio: number;
  win_rate: number;
  total_trades: number;
  period_days: number;
  max_drawdown: number;
  total_pnl: number;
  avg_win: number;
  avg_loss: number;
  meets_paper_threshold: boolean;
}

interface ValidationReport {
  status: "PASS" | "FAIL" | "INSUFFICIENT_DATA";
  metrics: PerformanceMetrics;
  thresholds: {
    profit_factor: number;
    sharpe_ratio: number;
    min_trades_required: number;
  };
  recommendation: string;
}

// ── Phase logic ───────────────────────────────────────────────────────────────

type PhaseStatus = "COMPLETE" | "IN_PROGRESS" | "NOT_STARTED";

interface PhaseData {
  number: 1 | 2 | 3;
  name: string;
  subtitle: string;
  targetDate: string;
  criteria: Array<{ label: string; met: boolean; detail: string }>;
  status: PhaseStatus;
}

function computePhases(metrics: PerformanceMetrics | null): PhaseData[] {
  const tradingDays = metrics?.period_days ?? 0;
  const totalTrades = metrics?.total_trades ?? 0;
  // win_rate from engine is 0–1 fraction; convert to percent for display/compare
  const winRatePct = metrics !== null ? metrics.win_rate * 100 : 0;
  const pf = metrics?.profit_factor ?? 0;
  const sharpe = metrics?.sharpe_ratio ?? 0;

  // Phase 1 criteria
  const p1_days = tradingDays >= 10;
  const p1_engine = metrics !== null; // engine responding = engine running
  const p1_allMet = p1_days && p1_engine;

  // Phase 2 criteria
  const p2_trades = totalTrades >= 30;
  const p2_winRate = winRatePct >= 50;
  const p2_pf = pf >= 1.5;
  const p2_metCount = [p2_trades, p2_winRate, p2_pf].filter(Boolean).length;
  const p2_allMet = p2_trades && p2_winRate && p2_pf;

  // Phase 3 criteria
  const p3_trades = totalTrades >= 60;
  const p3_winRate = winRatePct >= 55;
  const p3_pf = pf >= 2.0;
  const p3_sharpe = sharpe >= 1.5;
  const p3_metCount = [p3_trades, p3_winRate, p3_pf, p3_sharpe].filter(Boolean).length;
  const p3_allMet = p3_trades && p3_winRate && p3_pf && p3_sharpe;

  function p2Status(): PhaseStatus {
    if (p2_allMet) return "COMPLETE";
    if (p2_metCount >= 1) return "IN_PROGRESS";
    return "NOT_STARTED";
  }

  function p3Status(): PhaseStatus {
    if (p3_allMet) return "COMPLETE";
    if (p3_metCount >= 2) return "IN_PROGRESS";
    return "NOT_STARTED";
  }

  return [
    {
      number: 1,
      name: "Data Collection",
      subtitle: "First 2 weeks",
      targetDate: "March 2026",
      criteria: [
        {
          label: "Trading Days",
          met: p1_days,
          detail: `${tradingDays}/10 days`,
        },
        {
          label: "Engine Running",
          met: p1_engine,
          detail: metrics !== null ? "Online" : "Offline",
        },
      ],
      status: p1_allMet ? "COMPLETE" : "IN_PROGRESS",
    },
    {
      number: 2,
      name: "Statistical Validation",
      subtitle: "Weeks 3–4",
      targetDate: "April 2026",
      criteria: [
        {
          label: "Total Trades",
          met: p2_trades,
          detail: `${totalTrades}/30`,
        },
        {
          label: "Win Rate",
          met: p2_winRate,
          detail: `${winRatePct.toFixed(1)}% / 50%`,
        },
        {
          label: "Profit Factor",
          met: p2_pf,
          detail: `${pf.toFixed(2)} / 1.50`,
        },
      ],
      status: p2Status(),
    },
    {
      number: 3,
      name: "Extended Validation",
      subtitle: "Weeks 5–8",
      targetDate: "May 2026",
      criteria: [
        {
          label: "Total Trades",
          met: p3_trades,
          detail: `${totalTrades}/60`,
        },
        {
          label: "Win Rate",
          met: p3_winRate,
          detail: `${winRatePct.toFixed(1)}% / 55%`,
        },
        {
          label: "Profit Factor",
          met: p3_pf,
          detail: `${pf.toFixed(2)} / 2.00`,
        },
        {
          label: "Sharpe Ratio",
          met: p3_sharpe,
          detail: `${sharpe.toFixed(2)} / 1.50`,
        },
      ],
      status: p3Status(),
    },
  ];
}

function currentPhaseLabel(phases: PhaseData[]): string {
  for (const phase of phases) {
    if (phase.status !== "COMPLETE") {
      return `PHASE ${phase.number} — ${phase.name}`;
    }
  }
  return "READY FOR LIVE";
}

function overallProgress(phases: PhaseData[]): number {
  // Total criteria across all phases
  const allCriteria = phases.flatMap((p) => p.criteria);
  if (allCriteria.length === 0) return 0;
  const met = allCriteria.filter((c) => c.met).length;
  return Math.round((met / allCriteria.length) * 100);
}

// ── Sub-components ────────────────────────────────────────────────────────────

function PhaseIcon({ status }: { status: PhaseStatus }) {
  if (status === "COMPLETE") {
    return <CheckCircle2 className="h-5 w-5 text-bull shrink-0" />;
  }
  if (status === "IN_PROGRESS") {
    return <ArrowRight className="h-5 w-5 text-info shrink-0" />;
  }
  return <Circle className="h-5 w-5 text-muted-foreground shrink-0" />;
}

function phaseBadgeVariant(status: PhaseStatus): "bull" | "info" | "neutral" {
  if (status === "COMPLETE") return "bull";
  if (status === "IN_PROGRESS") return "info";
  return "neutral";
}

function phaseStatusLabel(status: PhaseStatus): string {
  if (status === "COMPLETE") return "COMPLETE";
  if (status === "IN_PROGRESS") return "IN PROGRESS";
  return "NOT STARTED";
}

// ── Main Widget ───────────────────────────────────────────────────────────────

export function PhaseProgressWidget() {
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchData() {
      try {
        const data = await fetchEngine(`/analytics/performance`);
        if (!cancelled) {
          setReport(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Fetch failed");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchData();
    return () => {
      cancelled = true;
    };
  }, []);

  const metrics = report?.metrics ?? null;
  const phases = computePhases(metrics);
  const currentLabel = currentPhaseLabel(phases);
  const progress = overallProgress(phases);
  const isAllComplete = phases.every((p) => p.status === "COMPLETE");

  // Find current active phase for the header
  const activePhase = phases.find((p) => p.status !== "COMPLETE") ?? phases[phases.length - 1];

  return (
    <Card>
      <CardContent className="pt-5 pb-5">
        {/* Header */}
        <div className="flex items-start gap-3 mb-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-info/15 shrink-0">
            <Target className="h-4 w-4 text-info" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
              Paper Trading Phase Progress
            </p>
            <p className="text-xl font-bold text-foreground tracking-tight mt-0.5">
              {loading ? "Loading…" : currentLabel}
            </p>
            {!loading && !isAllComplete && (
              <p className="text-[11px] text-muted-foreground mt-0.5">
                Target: {activePhase.targetDate}
              </p>
            )}
          </div>
          {!loading && (
            <Badge
              variant={isAllComplete ? "bull" : "info"}
              className="text-xs px-3 py-1 font-mono tracking-wider shrink-0"
            >
              {progress}% COMPLETE
            </Badge>
          )}
        </div>

        {/* Error notice */}
        {error && (
          <div className="rounded-lg border border-warn/20 bg-warn/5 px-3 py-2 text-xs text-warn mb-4">
            Engine offline — showing last known state. ({error})
          </div>
        )}

        {/* Overall progress bar */}
        <div className="mb-5">
          <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                isAllComplete ? "bg-bull" : "bg-info"
              }`}
              style={{ width: `${loading ? 0 : progress}%` }}
            />
          </div>
          <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
            <span>0%</span>
            <span>Live Trading Target: June 2026</span>
            <span>100%</span>
          </div>
        </div>

        {/* Phase rows */}
        <div className="space-y-3">
          {phases.map((phase) => (
            <div
              key={phase.number}
              className={`rounded-lg border p-3 ${
                phase.status === "COMPLETE"
                  ? "border-bull/20 bg-bull/5"
                  : phase.status === "IN_PROGRESS"
                  ? "border-info/20 bg-info/5"
                  : "border-border bg-muted/20"
              }`}
            >
              {/* Phase header row */}
              <div className="flex items-center gap-2 mb-2">
                <PhaseIcon status={phase.status} />
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-semibold text-foreground">
                    Phase {phase.number} — {phase.name}
                  </span>
                  <span className="ml-2 text-[10px] text-muted-foreground">
                    {phase.subtitle} · {phase.targetDate}
                  </span>
                </div>
                <Badge variant={phaseBadgeVariant(phase.status)}>
                  {phaseStatusLabel(phase.status)}
                </Badge>
              </div>

              {/* Criteria list */}
              <div className="flex flex-wrap gap-x-4 gap-y-1 pl-7">
                {phase.criteria.map((criterion) => (
                  <div key={criterion.label} className="flex items-center gap-1">
                    <span
                      className={`text-xs font-mono ${
                        criterion.met ? "text-bull" : "text-muted-foreground"
                      }`}
                    >
                      {criterion.met ? "✓" : "○"}
                    </span>
                    <span
                      className={`text-xs ${
                        criterion.met ? "text-foreground" : "text-muted-foreground"
                      }`}
                    >
                      {criterion.label}:
                    </span>
                    <span
                      className={`text-xs font-mono ${
                        criterion.met ? "text-bull" : "text-muted-foreground"
                      }`}
                    >
                      {loading ? "—" : criterion.detail}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Footnote */}
        <p className="text-[10px] text-muted-foreground text-center mt-4">
          Live trading target: June 2026 · Endpoint: /analytics/performance
        </p>
      </CardContent>
    </Card>
  );
}
