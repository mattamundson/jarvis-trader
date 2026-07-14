"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Layers } from "lucide-react";
import { fetchEngine } from "@/lib/api";

interface TFSignal {
  timeframe: string;
  stc_value: number;
  stc_signal: "BULLISH" | "BEARISH" | "NEUTRAL";
  price: number;
  source: string;
  error?: string | null;
}

interface MTFData {
  symbol: string;
  alignment: string;
  confidence: number;
  recommendation: string;
  aligned_timeframes: number;
  total_timeframes: number;
  source: string;
  signals: TFSignal[];
}

const SIGNAL_CLS: Record<string, string> = {
  BULLISH: "text-green-500",
  BEARISH: "text-red-400",
  NEUTRAL: "text-muted-foreground",
};

const ALIGN_VARIANT: Record<string, "bull" | "bear" | "warn" | "neutral"> = {
  BULLISH: "bull",
  BEARISH: "bear",
  MIXED: "warn",
  NEUTRAL: "neutral",
};

export function MTFConfirmationWidget({ symbol = "MES" }: { symbol?: string }) {
  const [data, setData] = useState<MTFData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const payload: Record<string, unknown> = await fetchEngine(`/analytics/mtf?symbol=${symbol}`);
        // Normalize: engine returns `timeframes` dict, widget expects `signals` array
        if (payload && !payload.signals && payload.timeframes && typeof payload.timeframes === "object") {
          const signals: TFSignal[] = Object.entries(payload.timeframes as Record<string, unknown>).map(
            ([tf, val]) => {
              const v = val as Record<string, unknown>;
              return {
                timeframe: tf,
                stc_value: (v.stc_value as number) ?? 0,
                stc_signal: (v.stc_signal as "BULLISH" | "BEARISH" | "NEUTRAL") ?? "NEUTRAL",
                price: (v.price as number) ?? 0,
                source: (v.source as string) ?? "live",
              };
            }
          );
          setData({ ...(payload as unknown as MTFData), signals });
        } else {
          const normalized = payload as unknown as MTFData;
          setData({ ...normalized, signals: normalized.signals ?? [] });
        }
      } catch {
        setData(null);
      } finally {
        setLoading(false);
      }
    };
    load();
    const id = setInterval(load, 300_000);
    return () => clearInterval(id);
  }, [symbol]);

  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Layers className="h-4 w-4" />MTF Confirmation
          </CardTitle>
        </CardHeader>
        <CardContent><div className="animate-pulse h-16 bg-muted rounded" /></CardContent>
      </Card>
    );
  }

  if (!data) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Layers className="h-4 w-4" />MTF Confirmation
          </CardTitle>
        </CardHeader>
        <CardContent><p className="text-sm text-muted-foreground">Unavailable</p></CardContent>
      </Card>
    );
  }

  const variant = ALIGN_VARIANT[data.alignment] ?? "neutral";

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <Layers className="h-4 w-4" />MTF — {data.symbol}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {/* stub source must not read as a live aligned/misaligned call */}
            <Badge variant={data.source === "stub" ? "neutral" : variant}>{data.alignment}</Badge>
            {data.source === "stub" && (
              <span className="rounded border border-muted-foreground/30 bg-muted/20 px-1.5 py-0.5 font-mono text-[8px] font-bold uppercase tracking-widest text-muted-foreground/70">
                Not wired · Phase 3
              </span>
            )}
          </div>
          <span className="text-xs text-muted-foreground">
            {data.aligned_timeframes}/{data.total_timeframes} aligned
          </span>
        </div>
        <div className={`space-y-1.5 ${data.source === "stub" ? "opacity-50" : ""}`}>
          {data.signals.map((sig) => (
            <div key={sig.timeframe} className="flex items-center gap-2 text-xs">
              <span className="font-mono text-muted-foreground w-7">{sig.timeframe}</span>
              <div className="flex-1 h-1.5 rounded-full bg-muted">
                <div
                  className={`h-full rounded-full ${
                    sig.stc_signal === "BULLISH" ? "bg-green-500"
                    : sig.stc_signal === "BEARISH" ? "bg-red-400"
                    : "bg-yellow-500"
                  }`}
                  style={{ width: `${Math.min(sig.stc_value, 100)}%` }}
                />
              </div>
              <span className={`w-16 text-right ${SIGNAL_CLS[sig.stc_signal]}`}>
                {sig.stc_signal}
              </span>
              <span className="font-mono text-muted-foreground w-8 text-right">
                {sig.stc_value.toFixed(0)}
              </span>
            </div>
          ))}
        </div>
        <div className="pt-1 border-t flex items-center justify-between">
          <span className="text-xs text-muted-foreground">Recommendation</span>
          <span className={`text-xs font-semibold ${
            data.recommendation === "BUY" ? "text-green-500"
            : data.recommendation === "SELL" ? "text-red-400"
            : "text-muted-foreground"
          }`}>{data.recommendation}</span>
        </div>
      </CardContent>
    </Card>
  );
}
