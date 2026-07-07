"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { RefreshCw } from "lucide-react";
import { fetchEngine } from "@/lib/api";


// ── Types ──────────────────────────────────────────────────────────────────

interface TimeframeData {
  stc_value: number;
  stc_signal: string;
  price: number;
  source: string;
}

interface MtfData {
  symbol: string;
  recommendation: "BUY" | "SELL" | "WAIT";
  alignment: string;
  confidence: number;
  aligned_timeframes: number;
  total_timeframes: number;
  source: string;
  timeframes: {
    "1h"?: TimeframeData;
    "4h"?: TimeframeData;
    "1d"?: TimeframeData;
    [key: string]: TimeframeData | undefined;
  };
}

// ── Helpers ────────────────────────────────────────────────────────────────

const REC_VARIANT: Record<string, "bull" | "bear" | "warn"> = {
  BUY: "bull",
  SELL: "bear",
  WAIT: "warn",
};

function stcColorClass(value: number): string {
  if (value > 80) return "text-bear font-semibold";
  if (value < 20) return "text-bull font-semibold";
  return "text-foreground";
}

function stcLabel(value: number): string {
  if (value > 80) return "OB";
  if (value < 20) return "OS";
  return "";
}

function signalVariant(signal: string): "bull" | "bear" | "neutral" {
  const upper = signal.toUpperCase();
  if (upper === "LONG" || upper === "BUY") return "bull";
  if (upper === "SHORT" || upper === "SELL") return "bear";
  return "neutral";
}

// ── Component ──────────────────────────────────────────────────────────────

const TIMEFRAME_ORDER: Array<"1h" | "4h" | "1d"> = ["1h", "4h", "1d"];
const TIMEFRAME_LABEL: Record<string, string> = {
  "1h": "1 Hour",
  "4h": "4 Hour",
  "1d": "Daily",
};

export function CurrentSignalWidget({ symbol = "MES" }: { symbol?: string }) {
  const [data, setData] = useState<MtfData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const json = await fetchEngine<MtfData>(
        `/analytics/mtf?symbol=${encodeURIComponent(symbol)}`
      );
      setData(json);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fetch failed");
    } finally {
      setLoading(false);
    }
  }, [symbol]);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 120_000);
    return () => clearInterval(id);
  }, [fetchData]);

  const recVariant: "bull" | "bear" | "warn" =
    data ? (REC_VARIANT[data.recommendation] ?? "warn") : "warn";

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <CardTitle className="text-base font-semibold tracking-tight">
            STC Signal &mdash; {symbol}
          </CardTitle>
          <div className="flex items-center gap-2">
            {data && (
              <Badge variant={recVariant}>
                {data.recommendation}
              </Badge>
            )}
            <button
              type="button"
              onClick={fetchData}
              disabled={loading}
              className="text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40"
              aria-label="Refresh STC signal"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>
        {lastUpdated && (
          <p className="text-[11px] text-muted-foreground mt-0.5">
            Updated {lastUpdated.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}
            &nbsp;&bull;&nbsp;auto-refresh 2 min
          </p>
        )}
      </CardHeader>

      <CardContent>
        {error && (
          <p className="text-xs text-bear py-2">{error}</p>
        )}

        {!data && !error && loading && (
          <p className="text-xs text-muted-foreground py-2">Loading&hellip;</p>
        )}

        {data && (
          <>
            {/* Timeframe rows */}
            <div className="divide-y divide-border rounded-md border border-border overflow-hidden mb-3">
              <div className="grid grid-cols-4 gap-2 px-3 py-1.5 bg-muted/40 text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
                <span>Timeframe</span>
                <span className="text-right">STC</span>
                <span className="text-center">Signal</span>
                <span className="text-right">Price</span>
              </div>

              {TIMEFRAME_ORDER.map((tf) => {
                const row = data.timeframes[tf];
                if (!row) return null;
                const label = stcLabel(row.stc_value);
                return (
                  <div
                    key={tf}
                    className="grid grid-cols-4 gap-2 items-center px-3 py-2 text-sm"
                  >
                    {/* Timeframe label */}
                    <span className="font-mono text-xs text-muted-foreground">
                      {TIMEFRAME_LABEL[tf] ?? tf}
                    </span>

                    {/* STC value */}
                    <span className={`text-right font-mono text-xs ${stcColorClass(row.stc_value)}`}>
                      {row.stc_value.toFixed(1)}
                      {label && (
                        <span className="ml-1 text-[10px] opacity-75">({label})</span>
                      )}
                    </span>

                    {/* Signal badge */}
                    <span className="flex justify-center">
                      <Badge variant={signalVariant(row.stc_signal)}>
                        {row.stc_signal.toUpperCase()}
                      </Badge>
                    </span>

                    {/* Price */}
                    <span className="text-right font-mono text-xs text-muted-foreground">
                      {row.price != null
                        ? row.price.toLocaleString("en-US", {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2,
                          })
                        : "\u2014"}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Footer summary */}
            <div className="flex items-center gap-3 flex-wrap text-xs text-muted-foreground">
              <span>
                Confidence:{" "}
                <span className="font-semibold text-foreground">
                  {(data.confidence * 100).toFixed(0)}%
                </span>
              </span>
              <span className="text-border">|</span>
              <span>
                Aligned:{" "}
                <span className="font-semibold text-foreground">
                  {data.aligned_timeframes}/{data.total_timeframes} timeframes
                </span>
              </span>
              {data.source && (
                <>
                  <span className="text-border">|</span>
                  <span className="truncate">{data.source}</span>
                </>
              )}
            </div>

            {/* Provenance (P4.2): rule-based signal, not the LLM pipeline — flag the
                backend gap honestly rather than invent narrative reasoning. */}
            <p className="text-[11px] text-muted-foreground mt-2 leading-snug">
              Why: rule-based STC crossover with multi-timeframe alignment. No LLM
              pipeline reasoning is generated for this signal type.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
