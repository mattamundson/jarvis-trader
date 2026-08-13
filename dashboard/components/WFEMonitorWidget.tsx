"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import React, { useMemo } from "react";
import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle, TrendingDown } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";

interface WFESnapshot {
  symbol: string;
  week_start: string;
  trades: number;
  win_rate: number | null;
  profit_factor: number | null;
  sharpe: number | null;
  max_dd: number | null;
  wfe_baseline: number | null;
  divergence_warning: boolean;
  created_at: string;
}

interface WFESnapshotResponse {
  snapshots: WFESnapshot[];
  total_count: number;
}

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

function getBadgeVariant(
  pf: number | null,
  baseline: number | null
): "bull" | "bear" | "warn" | "info" | "neutral" {
  if (pf === null || baseline === null) {
    return "neutral";
  }
  const thresholdWarn = baseline * 0.5;
  const thresholdBull = baseline * 0.8;

  if (pf >= thresholdBull) {
    return "bull";
  } else if (pf >= thresholdWarn) {
    return "warn";
  } else {
    return "bear";
  }
}

function formatPercent(value: number | null): string {
  if (value === null) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function formatNumber(value: number | null, decimals = 2): string {
  if (value === null) return "—";
  return value.toFixed(decimals);
}

export function WFEMonitorWidget(): React.ReactNode {
  const {
    data: response,
    error,
    isLoading,
  } = useSWR<WFESnapshotResponse>("/wfe/snapshots", fetcher, {
    refreshInterval: POLL_INTERVAL.MINUTE, // Refresh every minute
    revalidateOnFocus: true,
  });

  const snapshots = useMemo(() => {
    if (!response?.snapshots) return [];
    // Sort by week_start DESC (most recent first) and created_at DESC
    return response.snapshots.sort((a, b) => {
      const weekDiff = new Date(b.week_start).getTime() - new Date(a.week_start).getTime();
      if (weekDiff !== 0) return weekDiff;
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });
  }, [response]);

  const hasWarnings = snapshots.some((s) => s.divergence_warning);

  if (error) {
    return (
      <Card className="border-red-500/50 bg-red-500/5">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-red-400">
            <AlertTriangle className="h-5 w-5" />
            WFE Monitor
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">Failed to load WFE snapshots</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className={hasWarnings ? "border-amber-500/50 bg-amber-500/5" : ""}>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            {hasWarnings && <AlertTriangle className="h-5 w-5 text-amber-400" />}
            WFE Monitor (Weekly Snapshots)
          </CardTitle>
          {isLoading && <span className="text-xs text-muted-foreground">loading...</span>}
        </div>
      </CardHeader>
      <CardContent>
        {snapshots.length === 0 ? (
          <div className="py-4 text-center text-xs text-muted-foreground">
            No weekly snapshots yet
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border">
                  <th className="px-2 py-2 text-left font-semibold text-muted-foreground">
                    Week
                  </th>
                  <th className="px-2 py-2 text-left font-semibold text-muted-foreground">
                    Symbol
                  </th>
                  <th className="px-2 py-2 text-right font-semibold text-muted-foreground">
                    Trades
                  </th>
                  <th className="px-2 py-2 text-right font-semibold text-muted-foreground">
                    PF
                  </th>
                  <th className="px-2 py-2 text-right font-semibold text-muted-foreground">
                    Sharpe
                  </th>
                  <th className="px-2 py-2 text-right font-semibold text-muted-foreground">
                    vs WFE
                  </th>
                  <th className="px-2 py-2 text-right font-semibold text-muted-foreground">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody>
                {snapshots.map((snapshot, idx) => (
                  <tr key={idx} className="border-b border-border/50 hover:bg-muted/50">
                    <td className="px-2 py-2 text-muted-foreground">{snapshot.week_start}</td>
                    <td className="px-2 py-2 font-semibold">{snapshot.symbol}</td>
                    <td className="px-2 py-2 text-right">{snapshot.trades}</td>
                    <td className="px-2 py-2 text-right">
                      {formatNumber(snapshot.profit_factor)}
                    </td>
                    <td className="px-2 py-2 text-right">
                      {formatNumber(snapshot.sharpe)}
                    </td>
                    <td className="px-2 py-2 text-right text-muted-foreground">
                      {snapshot.wfe_baseline
                        ? `${formatNumber(snapshot.profit_factor)} / ${formatNumber(snapshot.wfe_baseline)}`
                        : "—"}
                    </td>
                    <td className="px-2 py-2 text-right">
                      <Badge
                        variant={getBadgeVariant(
                          snapshot.profit_factor,
                          snapshot.wfe_baseline
                        )}
                      >
                        {snapshot.divergence_warning ? (
                          <span className="flex items-center gap-1">
                            <TrendingDown className="h-3 w-3" />
                            Divergence
                          </span>
                        ) : snapshot.profit_factor === null ? (
                          "No Data"
                        ) : (
                          "Tracking"
                        )}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {hasWarnings && (
          <div className="mt-4 rounded-lg border border-amber-500/50 bg-amber-500/10 p-3">
            <p className="text-xs text-amber-100">
              <strong>Divergence Alert:</strong> One or more symbols have live PF below 50% of
              their WFE baseline. Review performance and consider adjusting parameters.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
