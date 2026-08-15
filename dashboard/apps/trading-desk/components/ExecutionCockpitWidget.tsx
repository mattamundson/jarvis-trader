"use client";

import { useEffect, useState, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { RefreshCw, WifiOff, Radio, FlaskConical } from "lucide-react";
import { fetchEngine } from "@/lib/api";

// ── Types (mirror engine ExecutionCockpit) ─────────────────────────────────────

interface SymbolFidelity {
  symbol: string;
  fidelity_overall: string; // APPROVED | INSUFFICIENT_DATA | NOT_APPROVED
  checks_passing: number;
  checks_total: number;
  slippage_n: number;
  mean_abs_slippage_ticks: number | null;
  p95_abs_slippage_ticks: number | null;
}

interface PendingApprovals {
  count: number;
  oldest_age_min: number | null;
}

interface RecentFill {
  symbol: string;
  side: string;
  quantity: number;
  price: number;
  fill_time: string;
  order_ref: string;
}

interface ExecutionCockpit {
  generated_at: string;
  measuring_real_fills: boolean;
  pending_approvals: PendingApprovals;
  recent_fills: RecentFill[];
  open_trades: unknown[];
  symbols: SymbolFidelity[];
  note: string;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function fidelityVariant(overall: string): "bull" | "bear" | "warn" | "info" {
  if (overall === "APPROVED") return "bull";
  if (overall === "NOT_APPROVED") return "bear";
  return "info"; // INSUFFICIENT_DATA
}

function fmtTicks(v: number | null): string {
  return v == null ? "—" : v.toFixed(2);
}

// ── Component ───────────────────────────────────────────────────────────────────

export function ExecutionCockpitWidget() {
  const [data, setData] = useState<ExecutionCockpit | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const fetchStatus = useCallback(async () => {
    setRefreshing(true);
    try {
      const json = await fetchEngine<ExecutionCockpit>("/execution/fidelity-status");
      setData(json);
      setError(null);
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reach engine");
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 15_000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const engineOffline = error !== null && data === null;
  const measuring = data?.measuring_real_fills ?? false;
  const symbols = data?.symbols ?? [];
  const pending = data?.pending_approvals ?? { count: 0, oldest_age_min: null };
  const recentFills = data?.recent_fills ?? [];
  const openTrades = data?.open_trades ?? [];
  // A queued-but-aging approval means the fill chain is stalled.
  const approvalsStuck = pending.count > 0;

  return (
    <Card
      className={cn(
        "border-2 transition-colors",
        engineOffline
          ? "border-destructive/40"
          : measuring
          ? "border-bull/50 bg-bull/5"
          : "border-warn/50 bg-warn/5"
      )}
    >
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <div className="flex items-center gap-2">
          <CardTitle className="text-base font-semibold tracking-tight">
            Execution Cockpit
          </CardTitle>
          <span className="text-[10px] font-mono text-muted-foreground px-1.5 py-0.5 rounded border border-border">
            <RefreshCw className={cn("inline h-2.5 w-2.5 mr-1", refreshing && "animate-spin")} />
            15s
          </span>
        </div>

        <div className="flex items-center gap-2">
          {engineOffline ? (
            <Badge variant="bear">
              <WifiOff className="inline h-3 w-3 mr-1" />
              Engine offline
            </Badge>
          ) : measuring ? (
            <Badge variant="bull">
              <Radio className="inline h-3 w-3 mr-1" />
              LIVE FILLS
            </Badge>
          ) : (
            <Badge variant="warn">
              <FlaskConical className="inline h-3 w-3 mr-1" />
              SIMULATED
            </Badge>
          )}
          {!engineOffline && (
            <Badge variant={approvalsStuck ? "warn" : "info"}>
              {pending.count} pending
              {approvalsStuck && pending.oldest_age_min != null
                ? ` · ${pending.oldest_age_min}m`
                : ""}
            </Badge>
          )}
        </div>
      </CardHeader>

      <CardContent>
        {engineOffline && (
          <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 mb-3 text-sm text-destructive">
            <WifiOff className="h-4 w-4 shrink-0" />
            <span>Engine offline — cannot retrieve execution status: {error}</span>
          </div>
        )}

        {error && data !== null && (
          <p className="text-xs text-destructive mb-2">
            Warning: last refresh failed — {error}
          </p>
        )}

        {!engineOffline && (
          <>
            {/* Per-symbol fidelity + slippage */}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-muted-foreground">
                    <th className="text-left pb-2 font-medium">Symbol</th>
                    <th className="text-left pb-2 font-medium">Fidelity</th>
                    <th className="text-right pb-2 font-medium">Checks</th>
                    <th className="text-right pb-2 font-medium">Slip n</th>
                    <th className="text-right pb-2 font-medium">Mean</th>
                    <th className="text-right pb-2 font-medium">p95</th>
                  </tr>
                </thead>
                <tbody>
                  {symbols.length === 0 && (
                    <tr>
                      <td colSpan={6} className="py-4 text-center text-muted-foreground text-xs">
                        No symbol data
                      </td>
                    </tr>
                  )}
                  {symbols.map((s) => (
                    <tr key={s.symbol} className="border-t border-border">
                      <td className="py-2.5 pr-3 font-mono font-semibold text-foreground">
                        {s.symbol}
                      </td>
                      <td className="py-2.5 pr-3">
                        <Badge variant={fidelityVariant(s.fidelity_overall)}>
                          {s.fidelity_overall}
                        </Badge>
                      </td>
                      <td className="py-2.5 text-right font-mono tabular-nums text-foreground">
                        {s.checks_passing}/{s.checks_total}
                      </td>
                      <td className="py-2.5 text-right font-mono tabular-nums text-muted-foreground">
                        {s.slippage_n}
                      </td>
                      <td className="py-2.5 text-right font-mono tabular-nums text-foreground">
                        {fmtTicks(s.mean_abs_slippage_ticks)}
                      </td>
                      <td className="py-2.5 text-right font-mono tabular-nums text-foreground">
                        {fmtTicks(s.p95_abs_slippage_ticks)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Compact counters */}
            <div className="flex items-center gap-2 mt-3">
              <Badge variant="info">{openTrades.length} open</Badge>
              <Badge variant="info">{recentFills.length} recent JARVIS fills</Badge>
            </div>

            {/* Mode note */}
            {data?.note && (
              <p className="text-[11px] text-muted-foreground mt-2">{data.note}</p>
            )}
          </>
        )}

        <div className="flex items-center justify-between mt-3 pt-2 border-t border-border">
          <span className="text-[10px] text-muted-foreground font-mono">
            Auto-refreshes every 15s
          </span>
          {lastUpdated && (
            <span className="text-[10px] text-muted-foreground font-mono">
              Updated {lastUpdated}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
