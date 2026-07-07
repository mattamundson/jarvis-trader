"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  fetchApprovedPaperGates,
  type ApprovedInstrumentGateRow,
  type ApprovedPaperGatesResponse,
} from "@/lib/api";

const REFRESH_MS = 120_000;

export function MESRevalidationTracker() {
  const [payload, setPayload] = useState<ApprovedPaperGatesResponse | null>(null);
  const [mesRow, setMesRow] = useState<ApprovedInstrumentGateRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetchApprovedPaperGates();
      setPayload(r);
      const row = r.instruments?.find((i) => i.symbol?.toUpperCase() === "MES") ?? null;
      setMesRow(row);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load gates");
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
          <CardTitle className="text-sm font-medium text-zinc-300">MES revalidation</CardTitle>
        </CardHeader>
        <CardContent className="pb-3">
          <div className="h-20 animate-pulse rounded bg-zinc-800/80" />
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="border-red-900/40 bg-zinc-950/60">
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium text-zinc-300">MES revalidation</CardTitle>
        </CardHeader>
        <CardContent className="pb-3 text-xs text-red-400/90">{error}</CardContent>
      </Card>
    );
  }

  if (!mesRow) {
    return (
      <Card className="border-amber-900/50 bg-zinc-950/60">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 py-3">
          <CardTitle className="text-sm font-medium text-zinc-300">MES revalidation</CardTitle>
          <Badge variant="warn" className="text-[10px]">
            Not in gate set
          </Badge>
        </CardHeader>
        <CardContent className="space-y-2 pb-3 text-xs text-zinc-500">
          <p>
            MES is not listed on <span className="font-mono text-zinc-400">approved-paper-gates</span>. Canon:{" "}
            <strong className="text-zinc-300">DO NOT TRADE MES</strong> until Tier 3 WFE / validation sign-off.
          </p>
          {payload?.note && <p className="text-[11px] text-zinc-600">{payload.note}</p>}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-zinc-800 bg-zinc-950/60">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 py-3">
        <CardTitle className="text-sm font-medium text-zinc-300">MES — paper gates</CardTitle>
        <Badge variant={mesRow.overall_pass ? "bull" : "bear"} className="text-[10px]">
          {mesRow.overall_pass ? "All gates pass" : "Gates open"}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-2 pb-3 text-xs text-zinc-400">
        <div className="flex justify-between font-mono text-[11px]">
          <span>Trades</span>
          <span className="text-zinc-200">{mesRow.trade_count}</span>
        </div>
        <div className="flex justify-between font-mono text-[11px]">
          <span>Days w/ trades</span>
          <span className="text-zinc-200">{mesRow.days_with_trades}</span>
        </div>
        <ul className="mt-2 space-y-1 border-t border-zinc-800 pt-2">
          {mesRow.gates.map((g) => (
            <li key={g.name} className="flex items-center justify-between gap-2 font-mono text-[11px]">
              <span className="truncate text-zinc-500">{g.name}</span>
              <span className={g.passes ? "text-emerald-400" : "text-red-400"}>
                {g.current.toFixed(g.unit === "%" ? 1 : 2)}
                {g.unit} / {g.target}
                {g.unit}
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
