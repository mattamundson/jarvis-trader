"use client";

import { useEffect, useState, useCallback } from "react";
import { AlertTriangle, TrendingUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { fetchEngine } from "@/lib/api";


// ── Types ─────────────────────────────────────────────────────────────────────

type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

interface MtfTimeframeSignal {
  stc_value?: number | null;
  stc_signal?: string | null;
  price?: number | null;
  source?: string | null;
}

interface MtfAnalysisResponse {
  symbol?: string;
  recommendation?: string;   // "BUY" | "SELL" | "WAIT"
  alignment?: string;        // "BULLISH" | "BEARISH" | "NEUTRAL"
  confidence?: number;
  aligned_timeframes?: number;
  total_timeframes?: number;
  source?: string;
  timeframes?: Record<string, MtfTimeframeSignal>;
}

// ── Badge variant helpers ─────────────────────────────────────────────────────

function alignmentVariant(alignment: string | undefined): BadgeVariant {
  const a = (alignment ?? "").toUpperCase();
  if (a === "BULLISH") return "bull";
  if (a === "BEARISH") return "bear";
  return "neutral";
}

function recommendationVariant(recommendation: string | undefined): BadgeVariant {
  const r = (recommendation ?? "").toUpperCase();
  if (r === "BUY") return "bull";
  if (r === "SELL") return "bear";
  return "warn";
}

function stcSignalVariant(signal: string | undefined | null): BadgeVariant {
  const s = (signal ?? "").toUpperCase();
  if (s === "LONG" || s === "BUY") return "bull";
  if (s === "SHORT" || s === "SELL") return "bear";
  return "neutral";
}

function confidenceBarClass(pct: number): string {
  if (pct >= 70) return "bg-[#00ff88]";
  if (pct >= 40) return "bg-[#ffcc00]";
  return "bg-[#ff4444]";
}

// ── Timeframe row ─────────────────────────────────────────────────────────────

function TimeframeRow({
  tf,
  data,
}: {
  tf: string;
  data: MtfTimeframeSignal;
}) {
  const stc = data.stc_value;
  const signal = data.stc_signal;
  const price = data.price;

  return (
    <div
      className={cn(
        "flex items-center justify-between py-1.5 px-0 font-mono text-xs border-b border-[#111]",
      )}
    >
      <span className="uppercase tracking-wider text-[10px] font-bold w-8 text-[#555]">
        {tf}
      </span>
      <span className="tabular-nums text-[#888]">
        {price != null ? `$${price.toFixed(2)}` : "--"}
      </span>
      <span className="tabular-nums text-[#888]">
        STC: {stc != null ? stc.toFixed(1) : "--"}
      </span>
      <Badge variant={stcSignalVariant(signal)}>
        {signal ?? "--"}
      </Badge>
    </div>
  );
}

// ── Main Widget ───────────────────────────────────────────────────────────────

export function MarketRegimeWidget() {
  const [data, setData] = useState<MtfAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const payload = await fetchEngine(`/analytics/mtf?symbol=MES`, {
        cache: "no-store",
      });
      setData(payload);
      setError(null);
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unavailable");
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch on mount + every 5 minutes
  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 5 * 60_000);
    return () => clearInterval(id);
  }, [fetchData]);

  // ── Loading skeleton ─────────────────────────────────────────────────────────
  if (loading) {
    return (
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle>Market Regime</CardTitle>
          <div className="h-5 w-16 rounded-full bg-muted animate-pulse" />
        </CardHeader>
        <CardContent className="space-y-2 animate-pulse">
          <div className="h-6 w-full rounded bg-muted" />
          <div className="h-6 w-full rounded bg-muted" />
          <div className="h-6 w-full rounded bg-muted" />
        </CardContent>
      </Card>
    );
  }

  // ── Error / unavailable state ────────────────────────────────────────────────
  if (error || !data) {
    return (
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle>Market Regime</CardTitle>
          <Badge variant="neutral">OFFLINE</Badge>
        </CardHeader>
        <CardContent>
          <div
            className="rounded-lg px-3 py-3 font-mono text-xs flex items-center gap-2 bg-[#ff444410] border border-[#ff444430] text-[#ff8888]"
          >
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            Market analysis unavailable
            {error && (
              <span className="text-[10px] opacity-70">— {error}</span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-3">
            Refreshes every 5m
          </p>
        </CardContent>
      </Card>
    );
  }

  // ── Derived values ───────────────────────────────────────────────────────────
  const alignment = data.alignment ?? "NEUTRAL";
  const recommendation = data.recommendation ?? "WAIT";
  const confidence = data.confidence ?? 0;
  const alignedTf = data.aligned_timeframes ?? 0;
  const totalTf = data.total_timeframes ?? 0;
  const symbol = data.symbol ?? "MES";
  const timeframes = data.timeframes ?? {};
  const tfKeys = Object.keys(timeframes).sort(); // e.g. ["1d", "1h", "4h"]

  const confidencePct = Math.round(confidence * 100);

  return (
    <Card>
      {/* Header */}
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-muted-foreground" />
          <CardTitle>Market Regime</CardTitle>
          <span
            className="font-mono text-[9px] px-1.5 py-0.5 rounded border border-[#00d4ff33] bg-[#00d4ff10] text-[#00d4ff]"
          >
            {symbol}
          </span>
        </div>
        <Badge variant={alignmentVariant(alignment)}>
          {alignment}
        </Badge>
      </CardHeader>

      <CardContent className="space-y-0">
        {/* Recommendation row */}
        <div className="flex items-center justify-between py-2 border-b border-border">
          <span className="text-xs text-muted-foreground">Recommendation</span>
          <Badge variant={recommendationVariant(recommendation)}>
            {recommendation}
          </Badge>
        </div>

        {/* Confidence row */}
        <div className="flex items-center justify-between py-2 border-b border-border">
          <span className="text-xs text-muted-foreground">Confidence</span>
          <div className="flex items-center gap-2">
            <div className="h-1.5 w-20 rounded-full overflow-hidden bg-panel-border">
              <div
                className={cn(
                  "h-full rounded-full transition-all duration-500",
                  confidenceBarClass(confidencePct),
                )}
                style={{ width: `${confidencePct}%` }}
              />
            </div>
            <span className="font-mono text-sm tabular-nums">
              {confidencePct}%
            </span>
          </div>
        </div>

        {/* Alignment count row */}
        <div className="flex items-center justify-between py-2 border-b border-border">
          <span className="text-xs text-muted-foreground">
            Aligned timeframes
          </span>
          <span className="font-mono text-sm tabular-nums">
            {alignedTf}/{totalTf}
          </span>
        </div>

        {/* Per-timeframe breakdown */}
        {tfKeys.length > 0 && (
          <div className="pt-2">
            <p className="font-mono text-[10px] uppercase tracking-wider mb-1 text-[#555]">
              Timeframes
            </p>
            {tfKeys.map((tf) => (
              <TimeframeRow key={tf} tf={tf} data={timeframes[tf]} />
            ))}
          </div>
        )}

        {/* Provenance (P4.2): rule-based read, not the LLM pipeline — flag the
            backend gap honestly rather than invent narrative reasoning. */}
        <p className="text-[11px] text-muted-foreground pt-3 leading-snug">
          Why: rule-based regime from STC multi-timeframe alignment. No LLM pipeline
          reasoning is generated for this signal type.
        </p>

        {/* Footer */}
        <p className="text-xs text-muted-foreground mt-3">
          Refreshes every 5m
          {lastUpdated && (
            <span className="ml-2 opacity-60">· Updated {lastUpdated}</span>
          )}
        </p>
      </CardContent>
    </Card>
  );
}
