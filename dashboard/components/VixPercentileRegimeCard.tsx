"use client";

import React from "react";
import useSWR from "swr";
import { Activity, RefreshCw, TrendingDown, TrendingUp } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine, type VixPercentileRegime } from "@/lib/api";

const POLLING_INTERVAL_MS = 60_000; // 60s — VIX regime moves on daily bars

const fetcher = (): Promise<VixPercentileRegime> =>
  fetchEngine<VixPercentileRegime>("/regime/vix-percentile");

// Volatility tier -> badge variant. Higher vol = more cautionary color.
function tierVariant(
  tier: VixPercentileRegime["tier"]
): "bull" | "bear" | "warn" | "info" | "neutral" {
  switch (tier) {
    case "Crisis":
      return "bear";
    case "HighVol":
      return "warn";
    case "MidVol":
      return "info";
    case "LowVol":
      return "bull";
    default:
      return "neutral";
  }
}

function momentumVariant(
  momentum: VixPercentileRegime["momentum"]
): "bull" | "bear" | "neutral" {
  if (momentum === "Bull") return "bull";
  if (momentum === "Bear") return "bear";
  return "neutral";
}

export function VixPercentileRegimeCard() {
  const { data, error, isLoading, mutate } = useSWR<VixPercentileRegime>(
    "/regime/vix-percentile",
    fetcher,
    { refreshInterval: POLLING_INTERVAL_MS }
  );

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-muted-foreground" />
          VIX Percentile Regime
        </CardTitle>
        <button
          type="button"
          onClick={() => mutate()}
          className="text-muted-foreground hover:text-foreground"
          aria-label="Refresh VIX regime"
        >
          <RefreshCw className={isLoading ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
        </button>
      </CardHeader>
      <CardContent>
        {error ? (
          <p className="text-sm text-bear">Regime data unavailable.</p>
        ) : !data ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Tier</span>
              <Badge variant={tierVariant(data.tier)}>{data.tier}</Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Momentum</span>
              <Badge variant={momentumVariant(data.momentum)}>
                <span className="flex items-center gap-1">
                  {data.momentum === "Bull" ? (
                    <TrendingUp className="h-3 w-3" />
                  ) : data.momentum === "Bear" ? (
                    <TrendingDown className="h-3 w-3" />
                  ) : null}
                  {data.momentum}
                </span>
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">VIX</span>
              <span className="text-sm font-medium tabular-nums">
                {data.vix.toFixed(2)}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Percentile</span>
              <span className="text-sm font-medium tabular-nums">
                {data.vix_percentile.toFixed(0)}
                <span className="text-muted-foreground">th</span>
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Confidence</span>
              <span className="text-sm font-medium tabular-nums">
                {(data.confidence * 100).toFixed(0)}%
              </span>
            </div>
            <p className="pt-1 text-xs text-muted-foreground">
              {data.lookback}d percentile · {data.momentum_window}d momentum ·{" "}
              {data.price_symbol} · {data.n_vix_bars} bars
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
