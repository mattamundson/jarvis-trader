"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";
import { RawRecordBadge } from "@/components/RawRecordBadge";


interface CommissionStats {
  total_commissions: number;
  gross_pnl: number;
  net_pnl: number;
  by_symbol: Record<string, number>;
  trade_count: number;
  avg_commission_per_trade: number;
  rates: Record<string, number>;
}

export function CommissionTrackerWidget() {
  const [data, setData] = useState<CommissionStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const payload = await fetchEngine(`/portfolio/stats/commissions`);
        setData(payload);
      } catch {
        setData(null);
      } finally {
        setLoading(false);
      }
    };

    load();
    const id = setInterval(load, 300_000); // refresh every 5 minutes
    return () => clearInterval(id);
  }, []);

  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Commission Tracker</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="animate-pulse h-8 bg-muted rounded" />
            <div className="animate-pulse h-8 bg-muted rounded" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!data) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Commission Tracker</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Unable to load commission data</p>
        </CardContent>
      </Card>
    );
  }

  const totalCommissions = data.total_commissions ?? 0;
  const avgPerTrade = data.avg_commission_per_trade ?? 0;
  // data.gross_pnl / net_pnl / trade_count are the RAW un-deduped P&L figures
  // (gross +$3,899.97 across 19 re-logged rows) — the same fabrication this
  // migration removed elsewhere. They are NOT commission data, so they are not
  // shown here; honest P&L lives in the Profit Factor / Performance cards.
  const rawFills = data.trade_count ?? 0;
  const bySymbol = data.by_symbol ?? {};

  const headerBadgeVariant: "warn" | "neutral" =
    totalCommissions > 100 ? "warn" : "neutral";

  return (
    <Card>
      <CardHeader className="pb-2 flex flex-row items-center justify-between">
        <div className="flex items-center gap-2 flex-wrap">
          <CardTitle className="text-sm">Commission Tracker</CardTitle>
          {/* Honest-data caveat badge */}
          <RawRecordBadge className="text-[10px] font-normal" />
        </div>
        <Badge variant={headerBadgeVariant}>
          ${totalCommissions.toFixed(2)} Total
        </Badge>
      </CardHeader>
      <CardContent>
        {/* Caveat note */}
        <p className="text-[11px] text-muted-foreground border border-warn/30 bg-warn/5 rounded px-2 py-1.5 mb-3 leading-snug">
          Commission costs are from the un-deduped engine record (the deduped
          trade record carries no commission fields), so they may be over-counted.
          P&amp;L is intentionally omitted here — see the Profit Factor card for
          the honest figure.
        </p>

        {/* Commission-only stats grid */}
        <div className="grid grid-cols-2 gap-3 text-center">
          <div className="rounded bg-muted p-3">
            <p className="text-xs text-muted-foreground">Total Commissions</p>
            <p className="text-lg font-mono font-bold text-foreground">
              ${totalCommissions.toFixed(2)}
            </p>
          </div>
          <div className="rounded bg-muted p-3">
            <p className="text-xs text-muted-foreground">Avg / Fill</p>
            <p className="text-lg font-mono font-bold text-foreground">
              ${avgPerTrade.toFixed(2)}
            </p>
          </div>
        </div>

        {/* Secondary stats */}
        <div className="flex justify-between mt-3 text-sm">
          <span className="text-muted-foreground">Raw fills (un-deduped)</span>
          <span className="font-mono">{rawFills}</span>
        </div>

        {/* Per-symbol breakdown */}
        {Object.keys(bySymbol).length > 0 && (
          <div className="mt-3 border-t border-border pt-2 space-y-1">
            <p className="text-xs text-muted-foreground mb-1">By symbol</p>
            {Object.entries(bySymbol).map(([sym, cost]) => (
              <div key={sym} className="flex justify-between text-xs">
                <span className="font-mono text-muted-foreground">{sym}</span>
                <span className="font-mono">${(cost ?? 0).toFixed(2)}</span>
              </div>
            ))}
          </div>
        )}

        {/* Commission impact note */}
        {totalCommissions > 0 && avgPerTrade > 0 && (
          <p className="text-xs text-muted-foreground mt-2 border-t border-border pt-2">
            Commission drag: ${totalCommissions.toFixed(2)} total cost reduces net P&L
          </p>
        )}

        <p className="text-xs text-muted-foreground mt-2">Refreshes every 5m</p>
      </CardContent>
    </Card>
  );
}
