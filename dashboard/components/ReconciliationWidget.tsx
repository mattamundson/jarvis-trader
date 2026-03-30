"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { RefreshCw, CheckCircle2, AlertTriangle, XCircle } from "lucide-react";

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

export function ReconciliationWidget() {
  const [data, setData] = useState<ReconcileResult | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await fetch("http://localhost:8010/ib/reconcile");
      if (!res.ok) throw new Error();
      setData(await res.json());
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, []);

  const statusInfo = data ? (STATUS_BADGE[data.status] ?? STATUS_BADGE.unknown) : STATUS_BADGE.unknown;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <RefreshCw className="h-4 w-4" />
            Position Reconciliation
          </CardTitle>
          <Button variant="ghost" size="sm" onClick={load} disabled={loading} className="h-7 w-7 p-0">
            <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {!data ? (
          <p className="text-sm text-muted-foreground">Unavailable</p>
        ) : (
          <>
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
                {m.symbol}: paper={m.paper_qty} IB={m.ib_qty} (&#916;{m.delta > 0 ? "+" : ""}{m.delta})
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
          </>
        )}
      </CardContent>
    </Card>
  );
}
