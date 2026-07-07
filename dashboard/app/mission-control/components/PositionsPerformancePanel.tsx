"use client";

import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { UnrealizedPosition } from "@/lib/api";
import { fetcher, formatPct, formatUsd, LoadingRows, UnreachableNote } from "./shared";

// Mirrors engine/routers/portfolio_router.py paper_performance() response —
// {"performance": {...}}. No Sharpe field is returned by this endpoint (the
// /portfolio/paper/performance route computes PF/win-rate/max-dd only), so
// the panel shows Sharpe as unavailable rather than fabricating a value.
interface PaperPerformanceLive {
  total_pnl?: number;
  win_rate?: number;
  profit_factor?: number | null;
  num_trades?: number;
  num_open?: number;
  max_dd?: number;
  unrealized_pnl?: number;
  total_pnl_including_open?: number;
}

interface PaperPerformanceResponse {
  performance: PaperPerformanceLive;
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "bull" | "bear" }) {
  const toneCls = tone === "bull" ? "text-bull" : tone === "bear" ? "text-bear" : "text-foreground";
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`font-mono text-sm font-semibold ${toneCls}`}>{value}</p>
    </div>
  );
}

export function PositionsPerformancePanel() {
  const {
    data: positions,
    error: posError,
    isLoading: posLoading,
  } = useSWR<UnrealizedPosition[]>("/portfolio/paper/positions/unrealized", fetcher, {
    refreshInterval: 15_000,
  });

  const {
    data: perfResp,
    error: perfError,
    isLoading: perfLoading,
  } = useSWR<PaperPerformanceResponse>("/portfolio/paper/performance", fetcher, {
    refreshInterval: 15_000,
  });

  const perf = perfResp?.performance;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Positions &amp; Paper Performance</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {perfError ? (
          <UnreachableNote endpoint="/portfolio/paper/performance" />
        ) : perfLoading ? (
          <LoadingRows rows={1} />
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat
              label="Cum P&L"
              value={formatUsd(perf?.total_pnl)}
              tone={(perf?.total_pnl ?? 0) >= 0 ? "bull" : "bear"}
            />
            <Stat label="Win Rate" value={perf?.win_rate != null ? formatPct(perf.win_rate) : "—"} />
            <Stat
              label="Profit Factor"
              value={perf?.profit_factor != null ? perf.profit_factor.toFixed(2) : "—"}
            />
            <Stat label="Trades" value={String(perf?.num_trades ?? 0)} />
          </div>
        )}
        {perf && (
          <p className="text-[10px] text-muted-foreground">
            Sharpe not returned by /portfolio/paper/performance — NOT VERIFIED / unavailable here.
          </p>
        )}

        {posError ? (
          <UnreachableNote endpoint="/portfolio/paper/positions/unrealized" />
        ) : posLoading ? (
          <LoadingRows rows={3} />
        ) : !positions || positions.length === 0 ? (
          <p className="text-xs text-muted-foreground">No open paper positions.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground border-b border-border">
                  <th className="py-1 pr-3 font-medium">Symbol</th>
                  <th className="py-1 pr-3 font-medium">Dir</th>
                  <th className="py-1 pr-3 font-medium text-right">Entry</th>
                  <th className="py-1 pr-3 font-medium text-right">Stop</th>
                  <th className="py-1 pr-3 font-medium text-right">Target</th>
                  <th className="py-1 font-medium text-right">Unrealized</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.trade_id} className="border-b border-border/50 last:border-0">
                    <td className="py-1.5 pr-3 font-semibold">{p.symbol}</td>
                    <td className="py-1.5 pr-3">
                      <Badge variant={p.direction?.toUpperCase() === "SHORT" ? "bear" : "bull"}>
                        {p.direction}
                      </Badge>
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono">
                      {p.entry_price != null ? p.entry_price.toFixed(2) : "—"}
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono">
                      {p.stop_loss != null ? p.stop_loss.toFixed(2) : "—"}
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono">
                      {p.take_profit != null ? p.take_profit.toFixed(2) : "—"}
                    </td>
                    <td
                      className={`py-1.5 text-right font-mono ${
                        (p.unrealized_pnl ?? 0) >= 0 ? "text-bull" : "text-bear"
                      }`}
                    >
                      {formatUsd(p.unrealized_pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
