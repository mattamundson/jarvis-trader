"use client";

import useSWR from "swr";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchCorrelationPreview } from "@/lib/api";

const REFRESH_MS = 60_000;
const SYMBOLS = ["MES", "MGC", "MCL", "MNQ"];

function corrBadgeVariant(rho: number): "bear" | "warn" | "neutral" {
  const abs = Math.abs(rho);
  if (abs >= 0.7) return "bear"; // highly correlated -> concentration risk
  if (abs >= 0.4) return "warn";
  return "neutral";
}

export function CorrelationPreviewWidget() {
  const { data, isLoading, error } = useSWR(
    ["correlation-preview", SYMBOLS],
    () => fetchCorrelationPreview(SYMBOLS),
    { refreshInterval: REFRESH_MS }
  );

  const pairs = data ? Object.entries(data.pairs) : [];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Portfolio Correlation (Preview)</CardTitle>
          <Badge variant={error ? "static" : "live"}>{error ? "static" : "live"}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <p className="text-xs text-muted-foreground/50 animate-pulse">Loading…</p>
        ) : error ? (
          <p className="text-xs text-red-400/70 italic">
            Correlation preview unavailable — engine may be unreachable
          </p>
        ) : (
          <>
            <div className="rounded-md border border-warn/30 bg-warn/5 px-3 py-2">
              <p className="text-[11px] text-warn">
                Preview only — NOT wired into live order sizing. The correlation-aware
                sizing trim in risk/portfolio_sizer.py is validated but not yet
                integrated into the order path; no live order has ever been resized
                for correlation.
              </p>
            </div>

            {pairs.length === 0 ? (
              <p className="text-xs text-muted-foreground/50 italic">
                No correlation pairs computable yet (insufficient overlapping bar data).
              </p>
            ) : (
              <div className="space-y-1">
                {pairs.map(([pair, rho]) => (
                  <div key={pair} className="flex items-center justify-between text-[11px]">
                    <span className="text-muted-foreground">{pair}</span>
                    <Badge variant={corrBadgeVariant(rho)}>{rho.toFixed(2)}</Badge>
                  </div>
                ))}
              </div>
            )}

            {data && data.omitted_pairs.length > 0 && (
              <p className="text-[10px] text-muted-foreground/40">
                No data: {data.omitted_pairs.join(", ")}
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
