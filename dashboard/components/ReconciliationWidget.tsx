"use client";

import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AlertCircle, RefreshCw, CheckCircle2, AlertTriangle, XCircle } from "lucide-react";
import { fetchEngine } from "@/lib/api";

interface ReconcileResult {
  ib_connected: boolean;
  matched: Array<{ symbol: string; quantity: number }>;
  ib_only: Array<{ symbol: string; quantity: number }>;
  paper_only: Array<{ symbol: string; quantity: number }>;
  mismatches: Array<{ symbol: string; paper_qty: number; ib_qty: number; delta: number }>;
  status: string;
  reconciled_at: string | null;
}

const STATUS_BADGE: Record<string, { variant: "bull" | "bear" | "warn" | "info" | "neutral"; label: string }> = {
  reconciled:      { variant: "bull",    label: "Reconciled" },
  no_positions:    { variant: "neutral", label: "No Positions" },
  mismatch:        { variant: "bear",    label: "Mismatch" },
  partial:         { variant: "warn",    label: "Partial" },
  ib_disconnected: { variant: "neutral", label: "IB Offline" },
  unknown:         { variant: "neutral", label: "Unknown" },
};

const fetcher = () => fetchEngine<ReconcileResult>("/ib/reconcile");

export function ReconciliationWidget() {
  const { data, error, isLoading } = useSWR<ReconcileResult>(
    "reconciliation/ib-reconcile",
    fetcher,
    { refreshInterval: 60_000, shouldRetryOnError: false }
  );

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <RefreshCw className="h-4 w-4 animate-spin" />
            Position Reconciliation
          </CardTitle>
        </CardHeader>
        <CardContent>
          <span className="text-xs text-muted-foreground animate-pulse">Loading…</span>
        </CardContent>
      </Card>
    );
  }

  if (error || !data) {
    const reason: string =
      error instanceof Error ? error.message : "Endpoint unavailable (GET /ib/reconcile)";
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <RefreshCw className="h-4 w-4 text-muted-foreground" />
            Position Reconciliation
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-start gap-3 rounded-lg border border-border bg-muted px-4 py-3">
            <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0 text-warn" />
            <div className="space-y-0.5">
              <p className="text-xs font-medium text-muted-foreground">
                Reconciliation data unavailable
              </p>
              <p className="text-[10px] text-muted-foreground/70 font-mono break-all">
                {reason}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  const statusInfo = STATUS_BADGE[data.status] ?? STATUS_BADGE.unknown;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <RefreshCw className="h-4 w-4" />
            Position Reconciliation
          </CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex items-center gap-2">
          <Badge variant={statusInfo.variant}>{statusInfo.label}</Badge>
          {!data.ib_connected && (
            <span className="text-xs text-muted-foreground">IB not connected</span>
          )}
        </div>
        {data.matched.length > 0 && (
          <div className="flex items-center gap-2 text-xs text-green-500">
            <CheckCircle2 className="h-3 w-3" />
            {data.matched.length} position{data.matched.length !== 1 ? "s" : ""} matched
          </div>
        )}
        {data.mismatches.map((m) => (
          <div key={m.symbol} className="flex items-center gap-2 text-xs text-red-400">
            <XCircle className="h-3 w-3" />
            {m.symbol}: paper={m.paper_qty} IB={m.ib_qty} (Δ{m.delta > 0 ? "+" : ""}{m.delta})
          </div>
        ))}
        {data.paper_only.map((p) => (
          <div key={p.symbol} className="flex items-center gap-2 text-xs text-yellow-500">
            <AlertTriangle className="h-3 w-3" />
            {p.symbol} in tracker only (qty {p.quantity})
          </div>
        ))}
        {data.ib_only.map((p) => (
          <div key={p.symbol} className="flex items-center gap-2 text-xs text-yellow-500">
            <AlertTriangle className="h-3 w-3" />
            {p.symbol} in IB only (qty {p.quantity})
          </div>
        ))}
        {data.reconciled_at && (
          <p className="text-xs text-muted-foreground pt-1">
            Updated {new Date(data.reconciled_at).toLocaleTimeString()}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
