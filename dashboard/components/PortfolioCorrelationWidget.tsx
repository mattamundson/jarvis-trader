"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchPortfolioRisk, type PortfolioRiskResponse } from "@/lib/api";

const REFRESH_MS = 30_000;

export function PortfolioCorrelationWidget() {
  const [data, setData] = useState<PortfolioRiskResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetchPortfolioRisk();
      setData(r);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load risk");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  if (loading) {
    return (
      <Card className="border-zinc-800 bg-zinc-950/60">
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium text-zinc-300">Portfolio correlation</CardTitle>
        </CardHeader>
        <CardContent className="pb-3">
          <div className="h-16 animate-pulse rounded bg-zinc-800/80" />
        </CardContent>
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card className="border-red-900/40 bg-zinc-950/60">
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium text-zinc-300">Portfolio correlation</CardTitle>
        </CardHeader>
        <CardContent className="pb-3 text-xs text-red-400/90">{error ?? "No data"}</CardContent>
      </Card>
    );
  }

  const positions = Object.entries(data.active_positions ?? {});
  const reduction = data.correlation_reduction_active;

  return (
    <Card className="border-zinc-800 bg-zinc-950/60">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 py-3">
        <CardTitle className="text-sm font-medium text-zinc-300">Portfolio correlation</CardTitle>
        <Badge variant={reduction ? "bear" : "neutral"} className="text-[10px] font-mono">
          {reduction ? "Sizing reduced" : "Normal max"}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-2 pb-3 text-xs text-zinc-400">
        <div className="flex justify-between gap-2 font-mono">
          <span>Open symbols</span>
          <span className="text-zinc-200">{data.open_symbol_count}</span>
        </div>
        <div className="flex justify-between gap-2 font-mono">
          <span>Max / correlated</span>
          <span className="text-zinc-200">
            {data.default_max_contracts} / {data.correlated_max_contracts}
          </span>
        </div>
        <div className="flex justify-between gap-2 font-mono">
          <span>Threshold</span>
          <span className="text-zinc-200">{data.correlation_threshold}</span>
        </div>
        {positions.length > 0 ? (
          <ul className="mt-1 border-t border-zinc-800 pt-2 font-mono text-[11px] text-zinc-500">
            {positions.map(([sym, qty]) => (
              <li key={sym} className="flex justify-between">
                <span>{sym}</span>
                <span className="text-emerald-400/90">{qty}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="border-t border-zinc-800 pt-2 text-[11px] text-zinc-600">No open positions in tracker</p>
        )}
      </CardContent>
    </Card>
  );
}
