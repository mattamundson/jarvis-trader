"use client";

import React from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CheckCircle2, ArrowRight, Circle, Target } from "lucide-react";
import {
  maxDrawdownPct,
  dedupCaveat,
  type HonestTradeSet,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

// ── Phase logic ───────────────────────────────────────────────────────────────

type PhaseStatus = "COMPLETE" | "IN_PROGRESS" | "NOT_STARTED";

interface PhaseData {
  number: 1 | 2 | 3;
  name: string;
  subtitle: string;
  targetDate: string;
  criteria: Array<{
    label: string;
    /** null = indeterminate (Sharpe) */
    met: boolean | null;
    detail: string;
  }>;
  status: PhaseStatus;
}

// Max drawdown as % of peak for the phase gate. Defers to the canonical
// running-peak helper; an all-losing record that never rose above its $0
// baseline counts as a full 100% drawdown for the gate (a % drawdown is
// undefined vs a non-positive peak — treat it as fully drawn down, not 0%).
function ddPctForGate(set: HonestTradeSet): number {
  const dd = maxDrawdownPct(set.trades) * 100;
  if (dd > 0) return dd;
  return set.net < 0 && set.trades.length > 0 ? 100 : 0;
}

function computePhases(set: HonestTradeSet | null): PhaseData[] {
  const totalTrades = set?.trades.length ?? 0;
  const winRatePct = set != null ? (set.winRate ?? 0) * 100 : 0;
  const pf = set?.profitFactor ?? 0;
  const ddPct = set != null ? ddPctForGate(set) : 0;

  // Phase 1 — Data Collection
  const p1_engine = set !== null;
  // Use trade count as a proxy for "10 trading days" (engine is up if we have trades)
  const p1_started = totalTrades >= 1;
  const p1_allMet = p1_engine && p1_started;

  // Phase 2 — Statistical Validation
  const p2_trades = totalTrades >= 30;
  const p2_winRate = winRatePct >= 50;
  const p2_pf = (set?.profitFactor ?? null) !== null && pf >= 1.5;
  const p2_metCount = [p2_trades, p2_winRate, p2_pf].filter(Boolean).length;
  const p2_allMet = p2_trades && p2_winRate && p2_pf;

  // Phase 3 — Extended Validation
  // Sharpe is indeterminate — excluded from pass count (null)
  const p3_trades = totalTrades >= 60;
  const p3_winRate = winRatePct >= 55;
  const p3_pf = (set?.profitFactor ?? null) !== null && pf >= 2.0;
  const p3_dd = ddPct <= 15;
  // count only decidable criteria
  const p3_decidable = [p3_trades, p3_winRate, p3_pf, p3_dd];
  const p3_metCount = p3_decidable.filter(Boolean).length;
  const p3_allMet = p3_trades && p3_winRate && p3_pf && p3_dd;

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
          label: "Trades Logged",
          met: p1_started,
          detail: `${totalTrades} recorded`,
        },
        {
          label: "Engine Running",
          met: p1_engine,
          detail: set !== null ? "Online" : "Offline",
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
          detail: set?.profitFactor != null ? `${(set.profitFactor ?? 0).toFixed(2)} / 1.50` : "— / 1.50",
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
          detail: set?.profitFactor != null ? `${(set.profitFactor ?? 0).toFixed(2)} / 2.00` : "— / 2.00",
        },
        {
          label: "Max Drawdown",
          met: p3_dd,
          detail: `${ddPct.toFixed(1)}% / ≤15%`,
        },
        {
          label: "Sharpe Ratio",
          // Indeterminate — broker-computed Sharpe not available from deduped record
          met: null,
          detail: "— (not computed)",
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
  // Only count decidable (non-null) criteria
  const allCriteria = phases.flatMap((p) => p.criteria).filter((c) => c.met !== null);
  if (allCriteria.length === 0) return 0;
  const met = allCriteria.filter((c) => c.met === true).length;
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
  const { honest: set, isLoading: loading, error: loadError } = useHonestTrades(0);
  const error = loadError ? (loadError instanceof Error ? loadError.message : String(loadError)) : null;

  const phases = computePhases(set);
  const currentLabel = currentPhaseLabel(phases);
  const progress = overallProgress(phases);
  const isAllComplete = phases.every((p) => p.status === "COMPLETE");

  const activePhase = phases.find((p) => p.status !== "COMPLETE") ?? phases[phases.length - 1];
  const caveat = set ? dedupCaveat(set) : null;

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
            Honest trade record unavailable — showing last known state. ({error})
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
                {phase.criteria.map((criterion) => {
                  const isIndeterminate = criterion.met === null;
                  const color = isIndeterminate
                    ? "text-muted-foreground"
                    : criterion.met
                    ? "text-bull"
                    : "text-muted-foreground";
                  return (
                    <div key={criterion.label} className="flex items-center gap-1">
                      <span className={`text-xs font-mono ${color}`}>
                        {isIndeterminate ? "–" : criterion.met ? "✓" : "○"}
                      </span>
                      <span
                        className={`text-xs ${
                          criterion.met ? "text-foreground" : "text-muted-foreground"
                        }`}
                      >
                        {criterion.label}:
                      </span>
                      <span className={`text-xs font-mono ${color}`}>
                        {loading ? "—" : criterion.detail}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        {/* Dedup caveat + footnote */}
        {caveat && (
          <p className="text-[10px] text-muted-foreground mt-3">{caveat}</p>
        )}
        {set?.caveats && set.caveats.length > 0 && (
          <p className="text-[10px] text-muted-foreground mt-1">
            {set.caveats.join(" · ")}
          </p>
        )}
        <p className="text-[10px] text-muted-foreground text-center mt-3">
          Sharpe excluded — not derivable from deduped trade record · Source: master/trading/realized
        </p>
      </CardContent>
    </Card>
  );
}
