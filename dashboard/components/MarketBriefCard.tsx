"use client";

import { AlertTriangle, BarChart3, CalendarClock, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useMarketBrief } from "@/hooks/useMarketBrief";
import type { MarketBriefSnapshot, MarketBriefSourceQuality } from "@/lib/marketBrief/types";

function fmt(n: number | null | undefined, dp = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

function pct(n: number | null | undefined, dp = 1): string {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(dp)}%`;
}

function ageLabel(ageSeconds: number | null | undefined): string {
  if (ageSeconds == null || Number.isNaN(ageSeconds)) return "age unknown";
  if (ageSeconds < 60) return `${ageSeconds}s old`;
  const minutes = Math.floor(ageSeconds / 60);
  if (minutes < 60) return `${minutes}m old`;
  const hours = ageSeconds / 3600;
  return `${hours.toFixed(hours >= 10 ? 0 : 1)}h old`;
}

function qualityVariant(quality: MarketBriefSourceQuality): "live" | "warn" | "static" {
  if (quality === "fresh") return "live";
  if (quality === "stale") return "warn";
  return "static";
}

function scenarioVariant(label: keyof MarketBriefSnapshot["scores"]["probabilities"]): "bull" | "warn" | "bear" {
  if (label === "continuation") return "bear";
  if (label === "rotation") return "warn";
  return "bull";
}

function dominantScenario(data: MarketBriefSnapshot): keyof MarketBriefSnapshot["scores"]["probabilities"] {
  const entries = Object.entries(data.scores.probabilities) as Array<[keyof MarketBriefSnapshot["scores"]["probabilities"], number]>;
  entries.sort((a, b) => b[1] - a[1]);
  return entries[0]?.[0] ?? "rotation";
}

function Stat({ label, value, className = "" }: { label: string; value: string; className?: string }) {
  return (
    <div className="rounded-lg border border-border bg-background/40 p-2">
      <div className="text-[10px] uppercase tracking-widest text-muted-foreground">{label}</div>
      <div className={`mt-1 font-mono text-sm font-bold tabular-nums ${className}`}>{value}</div>
    </div>
  );
}

function SymbolRow({ symbol, data }: { symbol: string; data: MarketBriefSnapshot["symbols"][string] | undefined }) {
  return (
    <div className="grid grid-cols-[52px_1fr_1fr_1fr] items-center gap-2 rounded-md border border-border bg-background/30 px-2 py-1.5 text-xs">
      <div className="font-mono font-bold text-foreground">{symbol.replace("=F", "")}</div>
      <div className="font-mono tabular-nums text-foreground">{fmt(data?.daily?.last_close)}</div>
      <div className={(data?.gap_pct ?? 0) < 0 ? "font-mono tabular-nums text-bear" : "font-mono tabular-nums text-bull"}>{pct(data?.gap_pct, 2)}</div>
      <div className="font-mono tabular-nums text-muted-foreground">{fmt(data?.pivots?.pivot)}</div>
    </div>
  );
}

function LoadingState() {
  return (
    <Card className="border-accent/20">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-accent">
          <BarChart3 className="h-4 w-4 animate-pulse" /> Market Brief Machine Score
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2 animate-pulse">
          <div className="h-5 rounded bg-muted" />
          <div className="h-20 rounded bg-muted" />
        </div>
      </CardContent>
    </Card>
  );
}

export function MarketBriefCard() {
  const { data, error, isLoading, mutate, isValidating } = useMarketBrief();

  if (isLoading && !data) return <LoadingState />;

  if (error || !data) {
    return (
      <Card className="border-bear/30 bg-bear/5">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-bear">
            <AlertTriangle className="h-4 w-4" /> Market Brief Machine Score
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-bear">Market brief route unavailable.</CardContent>
      </Card>
    );
  }

  const dominant = dominantScenario(data);
  const spy = data.symbols.SPY;
  const qqq = data.symbols.QQQ;
  const vix = data.symbols["^VIX"];

  return (
    <Card className="border-accent/25 bg-card/95 shadow-lg" data-testid="market-brief-card">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-accent">
              <BarChart3 className="h-4 w-4" /> Market Brief Machine Score
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              SPY / QQQ / VIX / ES / NQ read-only framing · {ageLabel(data.ageSeconds)}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="neutral" className="gap-1 border-dashed font-mono text-[10px]">
              <ShieldCheck className="h-3 w-3" /> ANALYSIS ONLY
            </Badge>
            <Badge variant={qualityVariant(data.sourceQuality)} className="font-mono text-[10px]">
              {data.sourceQuality.toUpperCase()}
            </Badge>
            <Badge variant={scenarioVariant(dominant)} className="font-mono text-[10px]">
              {dominant.toUpperCase()} {data.scores.probabilities[dominant].toFixed(1)}%
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
        <div className="grid grid-cols-3 gap-2">
          <Stat label="Continuation" value={`${data.scores.probabilities.continuation.toFixed(1)}%`} className="text-bear" />
          <Stat label="Rotation" value={`${data.scores.probabilities.rotation.toFixed(1)}%`} className="text-warn" />
          <Stat label="Failure" value={`${data.scores.probabilities.failure.toFixed(1)}%`} className="text-bull" />
        </div>

        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Stat label="SPY gap" value={pct(spy?.gap_pct, 2)} className={(spy?.gap_pct ?? 0) < 0 ? "text-bear" : "text-bull"} />
          <Stat label="QQQ gap" value={pct(qqq?.gap_pct, 2)} className={(qqq?.gap_pct ?? 0) < 0 ? "text-bear" : "text-bull"} />
          <Stat label="VIX Δ" value={pct(vix?.gap_pct, 2)} className={(vix?.gap_pct ?? 0) > 0 ? "text-warn" : "text-bull"} />
          <Stat label="Macro events" value={String(data.scores.macro_event_count ?? 0)} />
        </div>

        <div className="rounded-lg border border-border bg-background/30 p-3">
          <div className="mb-2 text-xs font-bold uppercase tracking-widest text-muted-foreground">Cross-asset levels</div>
          <div className="mb-1 grid grid-cols-[52px_1fr_1fr_1fr] gap-2 px-2 text-[10px] uppercase tracking-widest text-muted-foreground">
            <span>Sym</span><span>Close</span><span>Gap</span><span>Pivot</span>
          </div>
          <div className="space-y-1.5">
            {["ES=F", "NQ=F", "SPY", "QQQ", "^VIX"].map((symbol) => <SymbolRow key={symbol} symbol={symbol} data={data.symbols[symbol]} />)}
          </div>
        </div>

        {data.scores.notes?.length ? (
          <div className="rounded-lg border border-border bg-background/30 p-3 text-xs text-muted-foreground">
            {data.scores.notes.slice(0, 2).map((note) => <p key={note}>• {note}</p>)}
          </div>
        ) : null}

        {data.warnings.length > 0 && (
          <div className="rounded-lg border border-warn/30 bg-warn/5 p-2 text-[11px] text-warn">
            <CalendarClock className="mr-1 inline h-3 w-3" /> {data.warnings.slice(0, 2).join(" · ")}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
