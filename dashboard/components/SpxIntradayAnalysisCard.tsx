"use client";

import { Activity, AlertTriangle, BarChart3, ShieldCheck, TrendingDown, TrendingUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useSpxIntradayAnalysis } from "@/hooks/useSpxIntradayAnalysis";
import type { SpxIntradaySnapshot, SpxOperatorVerdict } from "@/lib/spxIntraday";

function fmt(n: number | null | undefined, dp = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

function pct(n: number | null | undefined, dp = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(dp)}%`;
}

function probability(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${n.toFixed(1)}%`;
}

function timeLabel(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function verdictVariant(label: SpxOperatorVerdict): "bull" | "bear" | "warn" | "info" | "neutral" {
  if (label === "CONTINUATION") return "bull";
  if (label === "REVERSAL_CONFIRMED") return "bear";
  if (label === "BREAKOUT_FAILURE_TEST") return "warn";
  if (label === "DATA_DEGRADED") return "bear";
  return "info";
}

function qualityVariant(quality: SpxIntradaySnapshot["sourceQuality"]): "live" | "static" | "warn" {
  if (quality === "fresh") return "live";
  if (quality === "stale") return "warn";
  return "static";
}

function metricClass(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "text-muted-foreground";
  if (n > 0) return "text-bull";
  if (n < 0) return "text-bear";
  return "text-muted-foreground";
}

function Stat({ label, value, className = "" }: { label: string; value: string; className?: string }) {
  return (
    <div className="rounded-lg border border-border bg-background/40 p-2">
      <div className="text-[10px] uppercase tracking-widest text-muted-foreground">{label}</div>
      <div className={`mt-1 font-mono text-sm font-bold tabular-nums ${className}`}>{value}</div>
    </div>
  );
}

function EvidenceList({ title, items, tone }: { title: string; items: string[]; tone: "bull" | "bear" }) {
  const color = tone === "bull" ? "text-bull" : "text-bear";
  return (
    <div className="rounded-lg border border-border bg-background/30 p-3">
      <div className={`mb-2 flex items-center gap-1.5 text-xs font-bold uppercase tracking-widest ${color}`}>
        {tone === "bull" ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
        {title}
      </div>
      <ul className="space-y-1.5 text-xs text-muted-foreground">
        {(items.length ? items : ["No confirmed evidence"]).map((item) => (
          <li key={item} className="leading-snug">• {item}</li>
        ))}
      </ul>
    </div>
  );
}

function LoadingState() {
  return (
    <Card className="border-accent/20">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-accent">
          <Activity className="h-4 w-4 animate-pulse" /> SPX Intraday Decision
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2 animate-pulse">
          <div className="h-5 rounded bg-muted" />
          <div className="h-20 rounded bg-muted" />
          <div className="h-20 rounded bg-muted" />
        </div>
      </CardContent>
    </Card>
  );
}

export function SpxIntradayAnalysisCard() {
  const { data, error, isLoading, mutate, isValidating } = useSpxIntradayAnalysis();

  if (isLoading && !data) return <LoadingState />;

  const snapshot = data;
  if (error || !snapshot) {
    return (
      <Card className="border-bear/30 bg-bear/5">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-bear">
            <AlertTriangle className="h-4 w-4" /> SPX Intraday Decision
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-bear">SPX analysis route unavailable.</CardContent>
      </Card>
    );
  }

  const pivot = snapshot.levels.find((l) => l.value === 7749.78);
  const buyerControl = snapshot.levels.find((l) => l.value === 7743.84);
  const immediate = snapshot.levels.find((l) => l.value === 7752.01);
  const closeAbovePivot = pivot ? snapshot.probabilityBands?.closeAbove[pivot.value.toFixed(2)] : null;
  const closeBelowBuyer = buyerControl ? snapshot.probabilityBands?.closeBelow[buyerControl.value.toFixed(2)] : null;
  const closeAboveImmediate = immediate ? snapshot.probabilityBands?.closeAbove[immediate.value.toFixed(2)] : null;

  return (
    <Card className="border-accent/25 bg-card/95 shadow-lg" data-testid="spx-intraday-analysis-card">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-accent">
              <BarChart3 className="h-4 w-4" /> SPX Intraday Decision
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              Live read-only EOD path model · {snapshot.proxyUsed.replace("_", " ")} · as of {timeLabel(snapshot.asOf)}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="neutral" className="gap-1 border-dashed font-mono text-[10px]">
              <ShieldCheck className="h-3 w-3" /> ANALYSIS ONLY
            </Badge>
            <Badge variant={qualityVariant(snapshot.sourceQuality)} className="font-mono text-[10px]">
              {snapshot.sourceQuality.toUpperCase()}
            </Badge>
            <Badge variant={verdictVariant(snapshot.verdict.label)} className="font-mono text-[10px]">
              {snapshot.verdict.label.replaceAll("_", " ")}
            </Badge>
            <button
              type="button"
              onClick={() => mutate()}
              disabled={isValidating}
              className="rounded-md border border-border px-2 py-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground hover:bg-muted disabled:opacity-50"
            >
              Refresh
            </button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="rounded-lg border border-border bg-background/40 p-3">
          <div className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Operator summary</div>
          <p className="mt-1 text-sm leading-relaxed text-foreground">{snapshot.verdict.summary}</p>
        </div>

        <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
          <Stat label="SPX" value={fmt(snapshot.currentPrice)} />
          <Stat label="Day high" value={fmt(snapshot.dayHigh)} />
          <Stat label="Day low" value={fmt(snapshot.dayLow)} />
          <Stat label="Day %" value={pct(snapshot.dayChangePct)} className={metricClass(snapshot.dayChangePct)} />
          <Stat label="VIX" value={fmt(snapshot.vix)} className={snapshot.vix != null && snapshot.vix > 20 ? "text-warn" : "text-muted-foreground"} />
          <Stat label="RSI 14" value={fmt(snapshot.rsi14, 1)} />
          <Stat label="VWAP" value={fmt(snapshot.vwap)} />
          <Stat label="σ rem" value={fmt(snapshot.probabilityBands?.blendedSigmaPoints)} />
        </div>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <div className="rounded-lg border border-border bg-background/30 p-3">
            <div className="mb-2 text-xs font-bold uppercase tracking-widest text-muted-foreground">Level ladder</div>
            <div className="space-y-1.5">
              {snapshot.levels.map((level) => (
                <div key={`${level.label}-${level.value}`} className="grid grid-cols-[1fr_auto_auto] items-center gap-2 text-xs">
                  <div className="truncate text-muted-foreground">{level.label}</div>
                  <div className="font-mono font-semibold tabular-nums text-foreground">{fmt(level.value)}</div>
                  <Badge variant={level.status === "lost" ? "bear" : level.status === "at" ? "warn" : "neutral"} className="justify-center font-mono text-[10px]">
                    {level.status} {level.distance >= 0 ? "+" : ""}{fmt(level.distance)}
                  </Badge>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-border bg-background/30 p-3">
            <div className="mb-2 text-xs font-bold uppercase tracking-widest text-muted-foreground">Probability map</div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <Stat label="Close > pivot" value={probability(closeAbovePivot)} />
              <Stat label="Close > 7752" value={probability(closeAboveImmediate)} />
              <Stat label="Close < buyer ctrl" value={probability(closeBelowBuyer)} />
              <Stat label="Median close" value={fmt(snapshot.probabilityBands?.p50)} />
            </div>
            {snapshot.probabilityBands && (
              <div className="mt-3 grid grid-cols-5 gap-1 text-center font-mono text-[10px] text-muted-foreground">
                <span>P10 {fmt(snapshot.probabilityBands.p10)}</span>
                <span>P25 {fmt(snapshot.probabilityBands.p25)}</span>
                <span>P50 {fmt(snapshot.probabilityBands.p50)}</span>
                <span>P75 {fmt(snapshot.probabilityBands.p75)}</span>
                <span>P90 {fmt(snapshot.probabilityBands.p90)}</span>
              </div>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <EvidenceList title="Bull evidence" items={snapshot.verdict.bullEvidence} tone="bull" />
          <EvidenceList title="Bear evidence" items={snapshot.verdict.bearEvidence} tone="bear" />
        </div>

        <div className="grid grid-cols-1 gap-2 md:grid-cols-4">
          {snapshot.scenarios.map((scenario) => (
            <div key={scenario.id} className="rounded-lg border border-border bg-background/30 p-2">
              <div className="font-mono text-lg font-bold text-foreground">{probability(scenario.probability)}</div>
              <div className="text-xs font-semibold text-muted-foreground">{scenario.label}</div>
              <div className="mt-1 font-mono text-[10px] text-muted-foreground">
                {fmt(scenario.expectedCloseBand[0])}–{fmt(scenario.expectedCloseBand[1])}
              </div>
            </div>
          ))}
        </div>

        {snapshot.warnings.length > 0 && (
          <div className="rounded-lg border border-warn/30 bg-warn/5 p-2 text-[11px] text-warn">
            {snapshot.warnings.slice(0, 2).join(" · ")}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
