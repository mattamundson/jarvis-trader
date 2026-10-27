"use client";

import React, { useMemo } from "react";
import { BarChart3, Target, TrendingUp, TrendingDown, Clock, Award } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  SAMPLE_SETUPS,
  computeSetupStats,
  groupBySetupType,
  groupByTimeOfDay,
  type SetupRecord,
} from "@/lib/setupScorecard";

const SETUP_GOAL = 20;

function fmtR(r: number): string {
  return r >= 0 ? `+${r.toFixed(1)}R` : `${r.toFixed(1)}R`;
}

function fmtPct(n: number): string {
  return `${n.toFixed(1)}%`;
}

function StatCard({
  label,
  value,
  sub,
  variant,
}: {
  label: string;
  value: string;
  sub?: string;
  variant: "bull" | "bear" | "neutral" | "warn";
}) {
  const colorMap = {
    bull: "text-bull",
    bear: "text-bear",
    neutral: "text-foreground",
    warn: "text-warn",
  };

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">
        {label}
      </p>
      <p className={`text-2xl font-bold font-mono ${colorMap[variant]}`}>
        {value}
      </p>
      {sub && (
        <p className="text-xs text-muted-foreground mt-1">{sub}</p>
      )}
    </div>
  );
}

function ProgressBar({ current, goal }: { current: number; goal: number }) {
  const pct = Math.min(100, (current / goal) * 100);
  const isComplete = current >= goal;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-foreground">
          Progress to Goal
        </span>
        <span className="text-sm font-mono">
          <span className={isComplete ? "text-bull" : "text-warn"}>
            {current}
          </span>
          <span className="text-muted-foreground"> / {goal}</span>
        </span>
      </div>
      <div className="h-3 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${
            isComplete ? "bg-bull" : "bg-warn"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function DistributionBar({
  label,
  values,
  color,
}: {
  label: string;
  values: number[];
  color: "bull" | "bear";
}) {
  if (values.length === 0) return null;

  const sorted = [...values].sort((a, b) => a - b);
  const min = sorted[0];
  const max = sorted[sorted.length - 1];
  const avg = values.reduce((a, b) => a + b, 0) / values.length;

  return (
    <div className="space-y-1">
      <p className="text-xs font-medium text-foreground">{label}</p>
      <div className="flex items-center gap-2 text-xs font-mono text-muted-foreground">
        <span>Min: {fmtR(min)}</span>
        <span>Avg: {fmtR(avg)}</span>
        <span>Max: {fmtR(max)}</span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full ${
            color === "bull" ? "bg-bull/60" : "bg-bear/60"
          }`}
          style={{ width: "100%" }}
        />
      </div>
    </div>
  );
}

export default function SetupScorecardClient() {
  const allStats = useMemo(() => computeSetupStats(SAMPLE_SETUPS), []);
  const bySetupType = useMemo(() => groupBySetupType(SAMPLE_SETUPS), []);
  const byTimeOfDay = useMemo(() => groupByTimeOfDay(SAMPLE_SETUPS), []);

  const mfeValues = SAMPLE_SETUPS.map((s) => s.mfe);
  const maeValues = SAMPLE_SETUPS.map((s) => s.mae);

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1400px] px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
              <Target className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h1 className="font-bold text-foreground">Setup Scorecard</h1>
              <p className="text-xs text-muted-foreground">
                Paper trade setup performance tracking
              </p>
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-6 py-6 space-y-6">
        <div className="rounded-lg border border-warn/40 bg-warn/5 px-4 py-2.5">
          <p className="text-xs text-warn">
            Demo fixture data — replace with real setup log when available.
          </p>
        </div>

        <div className="rounded-lg border border-border bg-card p-5">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Award className="h-5 w-5 text-accent" />
              <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                Goal Progress
              </h2>
            </div>
            <Badge variant={allStats.total >= SETUP_GOAL ? "bull" : "warn"}>
              {allStats.total >= SETUP_GOAL ? "Complete" : "In Progress"}
            </Badge>
          </div>
          <ProgressBar current={allStats.total} goal={SETUP_GOAL} />
        </div>

        <div>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            Overall Statistics
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
            <StatCard
              label="Total Setups"
              value={String(allStats.total)}
              variant="neutral"
            />
            <StatCard
              label="Hit Rate"
              value={fmtPct(allStats.hit_rate)}
              sub={`${allStats.wins}W / ${allStats.losses}L`}
              variant={allStats.hit_rate >= 50 ? "bull" : "warn"}
            />
            <StatCard
              label="Avg R"
              value={fmtR(allStats.avg_r)}
              variant={allStats.avg_r > 0 ? "bull" : "bear"}
            />
            <StatCard
              label="Expectancy"
              value={fmtR(allStats.expectancy)}
              variant={allStats.expectancy > 0 ? "bull" : "bear"}
            />
            <StatCard
              label="Best Setup"
              value={fmtR(allStats.best_r)}
              variant="bull"
            />
            <StatCard
              label="Worst Setup"
              value={fmtR(allStats.worst_r)}
              variant="bear"
            />
          </div>
        </div>

        <div>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            MFE / MAE Distribution
          </h2>
          <div className="rounded-lg border border-border bg-card p-5 space-y-4">
            <DistributionBar
              label="Maximum Favorable Excursion"
              values={mfeValues}
              color="bull"
            />
            <DistributionBar
              label="Maximum Adverse Excursion"
              values={maeValues}
              color="bear"
            />
          </div>
        </div>

        <div>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            By Setup Type
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from(bySetupType.entries()).map(([type, records]) => {
              const stats = computeSetupStats(records);
              return (
                <div
                  key={type}
                  className="rounded-lg border border-border bg-card p-4"
                >
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-semibold capitalize">
                      {type}
                    </h3>
                    <Badge variant="neutral">{stats.total}</Badge>
                  </div>
                  <div className="space-y-2 text-xs">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Hit Rate</span>
                      <span className="font-mono font-semibold">
                        {fmtPct(stats.hit_rate)}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Avg R</span>
                      <span
                        className={`font-mono font-semibold ${
                          stats.avg_r > 0 ? "text-bull" : "text-bear"
                        }`}
                      >
                        {fmtR(stats.avg_r)}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Expectancy</span>
                      <span
                        className={`font-mono font-semibold ${
                          stats.expectancy > 0 ? "text-bull" : "text-bear"
                        }`}
                      >
                        {fmtR(stats.expectancy)}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            By Time of Day
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
            {Array.from(byTimeOfDay.entries())
              .sort(([a], [b]) => {
                const order = ["premarket", "open", "midday", "close", "afterhours", "unknown"];
                return order.indexOf(a) - order.indexOf(b);
              })
              .map(([time, records]) => {
                const stats = computeSetupStats(records);
                return (
                  <div
                    key={time}
                    className="rounded-lg border border-border bg-card p-4"
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                      <h3 className="text-xs font-semibold capitalize">
                        {time}
                      </h3>
                    </div>
                    <div className="space-y-1 text-xs">
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Total</span>
                        <span className="font-mono">{stats.total}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Avg R</span>
                        <span
                          className={`font-mono font-semibold ${
                            stats.avg_r > 0 ? "text-bull" : "text-bear"
                          }`}
                        >
                          {fmtR(stats.avg_r)}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
          </div>
        </div>

        <div>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            Recent Setups
          </h2>
          <div className="rounded-lg border border-border bg-card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border bg-muted/30">
                    <th className="text-left px-4 py-2 text-muted-foreground font-semibold uppercase">
                      Date
                    </th>
                    <th className="text-left px-4 py-2 text-muted-foreground font-semibold uppercase">
                      Type
                    </th>
                    <th className="text-left px-4 py-2 text-muted-foreground font-semibold uppercase">
                      Dir
                    </th>
                    <th className="text-right px-4 py-2 text-muted-foreground font-semibold uppercase">
                      Entry
                    </th>
                    <th className="text-right px-4 py-2 text-muted-foreground font-semibold uppercase">
                      Exit
                    </th>
                    <th className="text-right px-4 py-2 text-muted-foreground font-semibold uppercase">
                      R
                    </th>
                    <th className="text-right px-4 py-2 text-muted-foreground font-semibold uppercase">
                      MFE
                    </th>
                    <th className="text-right px-4 py-2 text-muted-foreground font-semibold uppercase">
                      MAE
                    </th>
                    <th className="text-center px-4 py-2 text-muted-foreground font-semibold uppercase">
                      Outcome
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {SAMPLE_SETUPS.slice()
                    .reverse()
                    .map((setup, i) => (
                      <tr key={i} className="hover:bg-muted/20">
                        <td className="px-4 py-2.5 text-muted-foreground">
                          {setup.date}
                        </td>
                        <td className="px-4 py-2.5 capitalize">
                          {setup.setup_type}
                        </td>
                        <td className="px-4 py-2.5">
                          <Badge
                            variant={
                              setup.direction === "long" ? "bull" : "bear"
                            }
                          >
                            {setup.direction}
                          </Badge>
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono">
                          {setup.entry}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono">
                          {setup.exit}
                        </td>
                        <td
                          className={`px-4 py-2.5 text-right font-mono font-bold ${
                            setup.r > 0 ? "text-bull" : "text-bear"
                          }`}
                        >
                          {fmtR(setup.r)}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-bull">
                          {fmtR(setup.mfe)}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-bear">
                          {fmtR(setup.mae)}
                        </td>
                        <td className="px-4 py-2.5 text-center">
                          <Badge
                            variant={
                              setup.outcome === "win"
                                ? "bull"
                                : setup.outcome === "loss"
                                ? "bear"
                                : "neutral"
                            }
                          >
                            {setup.outcome}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <p className="text-[11px] text-muted-foreground text-center pb-4">
          Setup scorecard tracks pre-trade setups by type, time, and R multiples.
          No account info or dollar amounts.
        </p>
      </main>
    </div>
  );
}
