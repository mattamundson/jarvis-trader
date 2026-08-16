"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface Milestone {
  icon: string;
  label: string;
  description: string;
  date?: string;
  status: "DONE" | "IN PROGRESS" | "PENDING";
}

const MILESTONES: Milestone[] = [
  {
    icon: "✅",
    label: "Engine Built",
    description: "STC strategy + 5-agent pipeline complete",
    status: "DONE",
  },
  {
    icon: "🔄",
    label: "Paper Validation",
    description: "30+ trading days, PF≥2.0, Sharpe≥1.5",
    date: "Ongoing",
    status: "IN PROGRESS",
  },
  {
    icon: "📋",
    label: "Capital Allocation",
    description: "Allocate $10K–$25K IB account for MES",
    date: "TBD",
    status: "PENDING",
  },
  {
    icon: "🚀",
    label: "Live Trading",
    description: "Live routing plan: TBD, pending Amo decision",
    date: "TBD",
    status: "PENDING",
  },
];

function statusColor(status: Milestone["status"]): string {
  if (status === "DONE") return "text-green-400";
  if (status === "IN PROGRESS") return "text-yellow-400";
  return "text-muted-foreground";
}

export function GoLivePlanCard() {
  return (
    <Card className="border border-border bg-card">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <CardTitle className="text-base font-semibold tracking-tight">
            Go-Live Roadmap
          </CardTitle>
          <Badge variant="info" className="text-xs px-2.5 py-0.5 font-mono tracking-wider">
            PAPER PHASE
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-6">
        {/* Timeline */}
        <div className="relative">
          {/* Vertical connector line */}
          <div
            className="absolute left-[1.1rem] top-4 bottom-4 w-px bg-border"
            aria-hidden="true"
          />

          <ul className="space-y-0">
            {MILESTONES.map((m, idx) => (
              <li key={idx} className="relative flex gap-4 py-3">
                {/* Icon circle */}
                <div className="relative z-10 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-background border border-border text-base">
                  {m.icon}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0 pt-1">
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                    <span className="font-semibold text-sm text-foreground">
                      {m.label}
                    </span>
                    {m.date && (
                      <span className="text-xs text-muted-foreground font-mono">
                        {m.date}
                      </span>
                    )}
                    <span className={`text-xs font-semibold uppercase tracking-wide ml-auto ${statusColor(m.status)}`}>
                      {m.status}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {m.description}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </div>

        {/* Account comparison box */}
        <div className="grid grid-cols-2 gap-3">
          {/* Paper Account */}
          <div className="rounded-lg border border-border bg-muted/30 p-3 space-y-1">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
              Paper Account
            </p>
            <div className="space-y-1">
              <p className="text-sm font-semibold text-foreground">$10,000</p>
              <p className="text-xs text-muted-foreground">IB Gateway 4002</p>
              <p className="text-xs text-muted-foreground">Paper mode</p>
            </div>
          </div>

          {/* Live Account */}
          <div className="rounded-lg border border-border bg-muted/30 p-3 space-y-1">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
              Live Account
            </p>
            <div className="space-y-1">
              <p className="text-sm font-semibold text-foreground">$10,000–$25,000</p>
              <p className="text-xs text-muted-foreground">Live routing: TBD, pending Amo decision</p>
              <p className="text-xs text-muted-foreground">Live mode</p>
            </div>
          </div>
        </div>

        {/* Risk disclaimer */}
        <p className="text-[11px] text-muted-foreground leading-relaxed border-t border-border pt-3">
          Past paper performance does not guarantee live results. Start live with minimum position size (1 contract max).
        </p>
      </CardContent>
    </Card>
  );
}
