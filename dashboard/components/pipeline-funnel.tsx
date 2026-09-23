"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import useSWR from "swr";
import { fetchPipelineFunnel, PipelineFunnelResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

interface PipelineFunnelProps {
  className?: string;
}

type StageKey = "runs" | "signals" | "approved" | "executed" | "filled";

interface StageDef {
  key: StageKey;
  name: string;
  color: string;
  bgColor: string;
  borderColor: string;
  description: string;
  /** conversion_rates key that maps the PREVIOUS stage → this stage */
  rateKey: keyof PipelineFunnelResponse["conversion_rates"] | null;
}

const STAGES: StageDef[] = [
  {
    key: "runs",
    name: "Pipeline Runs",
    color: "text-blue-400",
    bgColor: "bg-blue-950",
    borderColor: "border-blue-800",
    description: "Total pipeline executions",
    rateKey: null,
  },
  {
    key: "signals",
    name: "Signals",
    color: "text-cyan-400",
    bgColor: "bg-cyan-950",
    borderColor: "border-cyan-800",
    description: "Buy/Sell decisions",
    rateKey: "runs_to_signals",
  },
  {
    key: "approved",
    name: "Approved",
    color: "text-green-400",
    bgColor: "bg-green-950",
    borderColor: "border-green-800",
    description: "Risk-approved signals",
    rateKey: "signals_to_approved",
  },
  {
    key: "executed",
    name: "Executed",
    color: "text-yellow-400",
    bgColor: "bg-yellow-950",
    borderColor: "border-yellow-800",
    description: "Trades placed",
    rateKey: "approved_to_executed",
  },
  {
    key: "filled",
    name: "Filled",
    color: "text-purple-400",
    bgColor: "bg-purple-950",
    borderColor: "border-purple-800",
    description: "Filled trades",
    rateKey: "executed_to_filled",
  },
];

function rateColorClass(rate: number | undefined, thresholds: [number, number] = [80, 50]): string {
  const r = rate ?? 0;
  if (r >= thresholds[0]) return "bg-green-950 text-green-400 border border-green-800";
  if (r >= thresholds[1]) return "bg-yellow-950 text-yellow-400 border border-yellow-800";
  return "bg-red-950 text-red-400 border border-red-800";
}

function FunnelCell({
  data,
  stage,
}: {
  data: PipelineFunnelResponse | undefined;
  stage: StageDef;
}) {
  const count = data?.funnel?.[stage.key];
  const rate = stage.rateKey
    ? data?.conversion_rates?.[stage.rateKey]
    : undefined;

  // A missing window (still loading, or its fetch failed) must never be
  // mistaken for zero fills — show an em dash so the gap is visible.
  return (
    <div className="flex flex-col items-end gap-0.5 min-w-[64px]">
      <Badge
        className={cn(
          "text-xs font-mono py-0 px-2",
          stage.bgColor,
          stage.borderColor
        )}
      >
        {count === undefined ? "—" : count.toLocaleString()}
      </Badge>
      {stage.rateKey && rate !== undefined && (
        <span
          className={cn(
            "text-[10px] font-mono leading-none",
            rate >= 80
              ? "text-green-400"
              : rate >= 50
                ? "text-yellow-400"
                : "text-red-400"
          )}
        >
          {rate.toFixed(1)}%
        </span>
      )}
    </div>
  );
}

function SkeletonCard({ className }: { className?: string }) {
  return (
    <Card className={cn("bg-slate-900/60 border border-cyan-900/50", className)}>
      <CardHeader className="pb-1.5 pt-3 px-4">
        <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
          <div className="w-2 h-2 bg-cyan-400 rounded-full animate-pulse" />
          PIPELINE FUNNEL
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-3">
        <div className="space-y-2">
          {STAGES.map((stage) => (
            <div
              key={stage.key}
              className="flex items-center justify-between p-2 bg-slate-800/30 rounded animate-pulse"
            >
              <div className="w-20 h-3 bg-slate-600 rounded" />
              <div className="flex gap-2">
                <div className="w-12 h-3 bg-slate-600 rounded" />
                <div className="w-12 h-3 bg-slate-600 rounded" />
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export function PipelineFunnel({ className }: PipelineFunnelProps) {
  const { data: funnel30, error: error30 } = useSWR<PipelineFunnelResponse>(
    "/analytics/pipeline-funnel?days=30",
    () => fetchPipelineFunnel(30),
    {
      refreshInterval: 300_000, // 5 minutes
      shouldRetryOnError: false,
    }
  );
  const { data: funnel90, error: error90 } = useSWR<PipelineFunnelResponse>(
    "/analytics/pipeline-funnel?days=90",
    () => fetchPipelineFunnel(90),
    {
      refreshInterval: 300_000,
      shouldRetryOnError: false,
    }
  );

  const isLoading = !funnel30 && !funnel90 && !error30 && !error90;
  const hasError = error30 && error90;

  if (isLoading) return <SkeletonCard className={className} />;

  if (hasError) {
    return (
      <Card className={cn("bg-slate-900/60 border border-red-900/50", className)}>
        <CardHeader className="pb-1.5 pt-3 px-4">
          <CardTitle className="text-xs font-mono text-red-400 tracking-widest flex items-center gap-1.5">
            <div className="w-2 h-2 bg-red-400 rounded-full" />
            PIPELINE FUNNEL · ERROR
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-3">
          <div className="text-xs text-red-400 font-mono">
            Failed to load funnel data
          </div>
        </CardContent>
      </Card>
    );
  }

  const details = funnel90?.details ?? funnel30?.details;
  const overall30 = funnel30?.conversion_rates?.overall_conversion;
  const overall90 = funnel90?.conversion_rates?.overall_conversion;

  return (
    <Card
      data-testid="pipeline-funnel-card"
      className={cn("bg-slate-900/60 border border-cyan-900/50", className)}
    >
      <CardHeader className="pb-1.5 pt-3 px-4">
        <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center justify-between gap-1.5">
          <span className="flex items-center gap-1.5">
            <div className="w-2 h-2 bg-cyan-400 rounded-full" />
            PIPELINE FUNNEL
          </span>
          <span className="text-[10px] text-slate-500 font-mono normal-case">
            30d → 90d
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-3 space-y-1.5">
        {/* Column headers */}
        <div className="flex items-center justify-between text-[10px] font-mono text-slate-500 uppercase tracking-wider px-1">
          <span>Stage</span>
          <div className="flex gap-2">
            <span className="w-[64px] text-right">30d</span>
            <span className="w-[64px] text-right">90d</span>
          </div>
        </div>

        {/* Funnel stages */}
        {STAGES.map((stage) => (
          <div
            key={stage.key}
            className={cn(
              "flex items-center justify-between p-2 rounded border",
              stage.borderColor
            )}
          >
            <div className="flex items-center gap-2 min-w-0">
              <div
                className={cn("w-2 h-2 rounded-full", stage.bgColor)}
              />
              <div className="min-w-0">
                <div className="font-mono text-xs text-white font-bold truncate">
                  {stage.name}
                </div>
                <div className="font-mono text-[10px] text-slate-500 truncate">
                  {stage.description}
                </div>
              </div>
            </div>
            <div className="flex gap-2 flex-shrink-0">
              <FunnelCell data={funnel30} stage={stage} />
              <FunnelCell data={funnel90} stage={stage} />
            </div>
          </div>
        ))}

        {/* Overall conversion rate */}
        <div className="pt-2 border-t border-cyan-800/30">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 bg-purple-400 rounded-full" />
              <div className="font-mono text-xs text-white font-bold">
                Overall Conversion
              </div>
            </div>
            <div className="flex gap-2">
              <Badge
                className={cn(
                  "text-xs font-mono py-0 px-2",
                  rateColorClass(overall30, [20, 10])
                )}
              >
                {overall30?.toFixed(1) ?? "—"}%
              </Badge>
              <Badge
                className={cn(
                  "text-xs font-mono py-0 px-2",
                  rateColorClass(overall90, [20, 10])
                )}
              >
                {overall90?.toFixed(1) ?? "—"}%
              </Badge>
            </div>
          </div>
        </div>

        {/* Human-review lanes — the "why so few trades" footnote */}
        {details && (
          <div className="text-[10px] text-slate-500 font-mono text-center pt-1">
            human-approved {details.human_approved ?? 0} · rejected{" "}
            {details.human_rejected ?? 0} (90d)
          </div>
        )}

        {/* Timestamp */}
        <div className="text-[10px] text-slate-500 font-mono text-center">
          Updated {new Date(funnel90?.timestamp ?? "").toLocaleTimeString()}
        </div>
      </CardContent>
    </Card>
  );
}
