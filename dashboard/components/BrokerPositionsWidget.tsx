"use client";

import useSWR from "swr";
import { Loader2, RefreshCw, WifiOff, CheckCircle, AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchEngine } from "@/lib/api";

// ── Types ──────────────────────────────────────────────────────────────────

interface BrokerPosition {
  symbol: string;
  quantity: number;
  avg_price: number;
  unrealized_pnl: number;
}

interface PaperPosition {
  symbol: string;
  direction: string;
  entry_price: number;
  quantity: number;
}

interface BrokerPositionsResponse {
  ibkr: { connected: boolean; positions: BrokerPosition[] };
  schwab: { connected: boolean; positions: BrokerPosition[] };
  paper: { positions: PaperPosition[] };
  reconciliation: { discrepancies: string[]; last_checked: string };
}

interface BrokerStatusResponse {
  ibkr_connected: boolean;
  schwab_connected: boolean;
}

// ── Helpers ────────────────────────────────────────────────────────────────

function positionsFetcher(path: string): Promise<BrokerPositionsResponse> {
  return fetchEngine<BrokerPositionsResponse>(path);
}

function statusFetcher(path: string): Promise<BrokerStatusResponse> {
  return fetchEngine<BrokerStatusResponse>(path);
}

function pnlColor(pnl: number): string {
  if (pnl > 0) return "text-bull";
  if (pnl < 0) return "text-bear";
  return "text-muted-foreground";
}

function directionLabel(qty: number): string {
  return qty > 0 ? "LONG" : qty < 0 ? "SHORT" : "FLAT";
}

// ── Sub-components ─────────────────────────────────────────────────────────

function PositionRow({ pos }: { pos: BrokerPosition }) {
  // Defensive: the broker feed can return null quantity / unrealized_pnl for a
  // position mid-update; coerce to 0 so a single null field can't crash the
  // whole home-page (was: null.toFixed -> error boundary took down the page).
  const qty = pos.quantity ?? 0;
  const upnl = pos.unrealized_pnl ?? 0;
  const dir = directionLabel(qty);
  const dirColor = qty > 0 ? "text-bull" : qty < 0 ? "text-bear" : "text-muted-foreground";
  return (
    <div className="flex items-center justify-between py-0.5 font-mono text-[11px]">
      <span className="text-foreground font-semibold w-14 shrink-0">{pos.symbol}</span>
      <span className={`w-6 text-center tabular-nums ${qty > 0 ? "text-bull" : "text-bear"}`}>
        {qty > 0 ? `+${qty}` : qty}
      </span>
      <span className={`w-10 text-center ${dirColor}`}>{dir}</span>
      <span className={`text-right tabular-nums ${pnlColor(upnl)}`}>
        {upnl >= 0 ? "+" : ""}${upnl.toFixed(2)}
      </span>
    </div>
  );
}

function ColumnEmpty({ reason }: { reason: "no_positions" | "not_connected" }) {
  return (
    <p className="font-mono text-[10px] text-muted-foreground/50 italic pt-1">
      {reason === "not_connected" ? "Not connected" : "No open positions"}
    </p>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

export function BrokerPositionsWidget() {
  const {
    data: positions,
    error: posError,
    isLoading: posLoading,
    mutate: mutatePositions,
  } = useSWR<BrokerPositionsResponse>("/brokers/positions", positionsFetcher, {
    refreshInterval: 10_000,
    shouldRetryOnError: false,
  });

  const { mutate: mutateStatus } = useSWR<BrokerStatusResponse>(
    "/brokers/status",
    statusFetcher,
    { refreshInterval: 5_000, shouldRetryOnError: false }
  );

  const handleRefresh = () => {
    mutatePositions();
    mutateStatus();
  };

  // ── Loading ─────────────────────────────────────────────────────────────

  if (posLoading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="font-mono">BROKER POSITIONS</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 text-xs text-muted-foreground animate-pulse">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            <span>Loading positions&hellip;</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  // ── Engine unreachable ──────────────────────────────────────────────────

  if (posError || !positions) {
    return (
      <Card className="border-bear/20">
        <CardHeader className="pb-2">
          <CardTitle className="font-mono">BROKER POSITIONS</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2">
            <WifiOff className="h-4 w-4 text-bear shrink-0" />
            <div className="space-y-0.5">
              <Badge variant="bear">ENGINE UNREACHABLE</Badge>
              <p className="text-[10px] text-muted-foreground">Cannot reach /brokers/positions</p>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  // ── Normal render ───────────────────────────────────────────────────────

  const ibkr = positions.ibkr;
  const schwab = positions.schwab;
  const paper = positions.paper;
  const recon = positions.reconciliation;

  const ibkrPnl = ibkr.positions.reduce((acc, p) => acc + p.unrealized_pnl, 0);
  const hasDiscrepancies = recon.discrepancies.length > 0;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="font-mono">BROKER POSITIONS</CardTitle>
          <Button size="sm" variant="ghost" onClick={handleRefresh} className="h-7 w-7 p-0">
            <RefreshCw className="h-3.5 w-3.5 text-muted-foreground" />
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* Two-column positions grid */}
        <div className="grid grid-cols-2 gap-3">
          {/* IBKR column */}
          <div className="space-y-1">
            <div className="flex items-center gap-1.5 mb-1.5">
              <p className="font-mono text-[10px] font-bold tracking-wider text-muted-foreground uppercase">
                IBKR Futures
              </p>
              <Badge variant={ibkr.connected ? "bull" : "neutral"} className="text-[9px] px-1 py-0">
                {ibkr.connected ? "LIVE" : "OFF"}
              </Badge>
            </div>
            <div className="border-t border-border/50 pt-1">
              {!ibkr.connected ? (
                <ColumnEmpty reason="not_connected" />
              ) : ibkr.positions.length === 0 ? (
                <ColumnEmpty reason="no_positions" />
              ) : (
                ibkr.positions.map((p) => <PositionRow key={p.symbol} pos={p} />)
              )}
            </div>
            {ibkr.connected && ibkr.positions.length > 0 && (
              <div className="pt-1 border-t border-border/30">
                <p className={`font-mono text-[11px] font-semibold tabular-nums ${pnlColor(ibkrPnl)}`}>
                  PnL: {ibkrPnl >= 0 ? "+" : ""}${ibkrPnl.toFixed(2)}
                </p>
              </div>
            )}
          </div>

          {/* Schwab column */}
          <div className="space-y-1">
            <div className="flex items-center gap-1.5 mb-1.5">
              <p className="font-mono text-[10px] font-bold tracking-wider text-muted-foreground uppercase">
                Schwab Eq/Opts
              </p>
              <Badge variant={schwab.connected ? "bull" : "neutral"} className="text-[9px] px-1 py-0">
                {schwab.connected ? "LIVE" : "OFF"}
              </Badge>
            </div>
            <div className="border-t border-border/50 pt-1">
              {!schwab.connected ? (
                <ColumnEmpty reason="not_connected" />
              ) : schwab.positions.length === 0 ? (
                <ColumnEmpty reason="no_positions" />
              ) : (
                schwab.positions.map((p) => <PositionRow key={p.symbol} pos={p} />)
              )}
            </div>
          </div>
        </div>

        {/* Paper positions footer */}
        {paper.positions.length > 0 && (
          <div className="border-t border-border pt-2">
            <p className="font-mono text-[10px] text-muted-foreground/70 leading-relaxed">
              <span className="text-accent font-semibold">PAPER:</span>{" "}
              {paper.positions
                .map((p) => `${p.symbol} ${p.direction.toUpperCase()} @ ${p.entry_price.toFixed(2)}`)
                .join(" \u00b7 ")}
            </p>
          </div>
        )}

        {/* Reconciliation line */}
        <div className="border-t border-border pt-2">
          <div className="flex items-center gap-1.5">
            {hasDiscrepancies ? (
              <>
                <AlertTriangle className="h-3.5 w-3.5 text-bear shrink-0" />
                <p className="font-mono text-[10px] text-bear">
                  Reconciliation: {recon.discrepancies.length} discrepanc{recon.discrepancies.length === 1 ? "y" : "ies"}
                </p>
              </>
            ) : (
              <>
                <CheckCircle className="h-3.5 w-3.5 text-bull shrink-0" />
                <p className="font-mono text-[10px] text-bull">Reconciliation: No discrepancies</p>
              </>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
