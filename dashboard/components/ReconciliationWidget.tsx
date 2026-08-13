"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AlertCircle, RefreshCw, CheckCircle2, AlertTriangle, XCircle } from "lucide-react";
import { fetchEngine } from "@/lib/api";

// ── Backend shape ────────────────────────────────────────────────────────────
// GET /brokers/positions (engine/routers/brokers_router.py::get_broker_positions).
// GT-25: this widget previously called GET /ib/reconcile, an endpoint that no
// longer exists on the engine (404) — the position-reconciliation logic now
// lives entirely under /brokers/positions, already consumed elsewhere by
// BrokerPositionsWidget.tsx. This widget adapts that same response into its
// own matched/ib_only/paper_only/mismatches presentation.

interface BrokerPosition {
  symbol: string;
  quantity: number;
  avg_price: number | null;
  market_price: number | null;
  unrealized_pnl: number | null;
  sec_type: string;
}

interface PaperPosition {
  trade_id: string;
  symbol: string;
  direction: "LONG" | "SHORT";
  quantity: number;
  entry_price: number | null;
  entry_time: string | null;
}

interface Discrepancy {
  symbol: string | null;
  type: string; // "paper_only" | "live_only" | "qty_mismatch" | "all_brokers_disconnected"
  detail: string;
  paper_qty?: number;
  live_qty?: number;
  delta?: number;
}

interface BrokerPositionsResponse {
  ibkr: { connected: boolean; positions: BrokerPosition[] };
  schwab: { connected: boolean; positions: BrokerPosition[] };
  paper: { positions: PaperPosition[] };
  reconciliation: {
    discrepancies: Discrepancy[];
    health: "ok" | "partial" | "blind";
    ibkr_queryable: boolean;
    schwab_queryable: boolean;
    last_checked: string;
  };
}

// Widget-local shape the render logic below is written against.
interface ReconcileResult {
  ib_connected: boolean;
  matched: Array<{ symbol: string; quantity: number }>;
  ib_only: Array<{ symbol: string; quantity: number }>;
  paper_only: Array<{ symbol: string; quantity: number }>;
  mismatches: Array<{ symbol: string; paper_qty: number; ib_qty: number; delta: number }>;
  status: string;
  reconciled_at: string | null;
}

function signedPaperQty(p: PaperPosition): number {
  const qty = Math.abs(p.quantity);
  return p.direction === "LONG" ? qty : -qty;
}

/** Reshape GET /brokers/positions into the flat contract this widget renders. */
function adapt(data: BrokerPositionsResponse): ReconcileResult {
  const livePositions = [...data.ibkr.positions, ...data.schwab.positions];
  const liveQtyBySymbol = new Map<string, number>();
  for (const p of livePositions) {
    liveQtyBySymbol.set(p.symbol.toUpperCase(), (liveQtyBySymbol.get(p.symbol.toUpperCase()) ?? 0) + p.quantity);
  }
  const paperQtyBySymbol = new Map<string, number>();
  for (const p of data.paper.positions) {
    const sym = p.symbol.toUpperCase();
    paperQtyBySymbol.set(sym, (paperQtyBySymbol.get(sym) ?? 0) + signedPaperQty(p));
  }

  const { discrepancies } = data.reconciliation;
  const flaggedSymbols = new Set(discrepancies.map((d) => d.symbol).filter((s): s is string => !!s));

  const mismatches = discrepancies
    .filter((d) => d.type === "qty_mismatch" && d.symbol)
    .map((d) => ({
      symbol: d.symbol as string,
      paper_qty: d.paper_qty ?? 0,
      ib_qty: d.live_qty ?? 0,
      delta: d.delta ?? 0,
    }));

  const paper_only = discrepancies
    .filter((d) => d.type === "paper_only" && d.symbol)
    .map((d) => ({ symbol: d.symbol as string, quantity: paperQtyBySymbol.get(d.symbol as string) ?? 0 }));

  const ib_only = discrepancies
    .filter((d) => d.type === "live_only" && d.symbol)
    .map((d) => ({ symbol: d.symbol as string, quantity: liveQtyBySymbol.get(d.symbol as string) ?? 0 }));

  const matched: Array<{ symbol: string; quantity: number }> = [];
  for (const sym of liveQtyBySymbol.keys()) {
    if (paperQtyBySymbol.has(sym) && !flaggedSymbols.has(sym)) {
      matched.push({ symbol: sym, quantity: liveQtyBySymbol.get(sym) ?? 0 });
    }
  }

  let status: string;
  if (data.reconciliation.health === "blind") {
    status = "ib_disconnected";
  } else if (mismatches.length > 0) {
    status = "mismatch";
  } else if (paper_only.length > 0 || ib_only.length > 0) {
    status = "partial";
  } else if (matched.length === 0) {
    status = "no_positions";
  } else {
    status = "reconciled";
  }

  return {
    ib_connected: data.ibkr.connected,
    matched,
    ib_only,
    paper_only,
    mismatches,
    status,
    reconciled_at: data.reconciliation.last_checked ?? null,
  };
}

const STATUS_BADGE: Record<string, { variant: "bull" | "bear" | "warn" | "info" | "neutral"; label: string }> = {
  reconciled:      { variant: "bull",    label: "Reconciled" },
  no_positions:    { variant: "neutral", label: "No Positions" },
  mismatch:        { variant: "bear",    label: "Mismatch" },
  partial:         { variant: "warn",    label: "Partial" },
  ib_disconnected: { variant: "neutral", label: "IB Offline" },
  unknown:         { variant: "neutral", label: "Unknown" },
};

const fetcher = async (): Promise<ReconcileResult> =>
  adapt(await fetchEngine<BrokerPositionsResponse>("/brokers/positions"));

export function ReconciliationWidget() {
  const { data, error, isLoading } = useSWR<ReconcileResult>(
    "reconciliation/brokers-positions",
    fetcher,
    { refreshInterval: POLL_INTERVAL.MINUTE, shouldRetryOnError: false }
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
      error instanceof Error ? error.message : "Endpoint unavailable (GET /brokers/positions)";
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
