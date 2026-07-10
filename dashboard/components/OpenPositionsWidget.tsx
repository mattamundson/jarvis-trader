"use client";

import { useEffect, useState, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { TrendingUp, TrendingDown, RefreshCw, WifiOff } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import { ProvenanceBadge } from "@/components/DataValue";
import { type DataEnvelope } from "@/lib/provenance";
import { useProvenance } from "@/lib/useProvenance";

// ── Types ──────────────────────────────────────────────────────────────────────

interface OpenPosition {
  trade_id?: string;
  symbol: string;
  action: string;          // "buy" | "sell" | "sell_short" | "buy_to_cover" | etc.
  quantity: number;
  entry_price: number;
  entry_time?: string;     // ISO-8601
  exit_price?: number | null;
  exit_time?: string | null;
  pnl?: number | null;
  notes?: string;
  is_open?: boolean;
  // Extended fields (present when added via add_paper_trade with DB)
  stop_loss?: number | null;
  take_profit?: number | null;
  // Live price fields — engine enriches /portfolio/paper/positions via the
  // same _compute_unrealized helper /portfolio and /portfolio/summary use.
  current_price?: number | null;
  unrealized_pnl?: number | null;
  // Data-provenance envelope (Phase 1) for current_price — see
  // engine/data/provenance.py / dashboard/lib/provenance.ts.
  is_live?: boolean;
  source?: string | null;
  as_of?: number | null;
  stale_after_s?: number;
}

// Fallback freshness window when a position predates the provenance envelope.
const DEFAULT_STALE_AFTER_S = 60;

/** Map an OpenPosition's mark fields to the canonical DataEnvelope shape. */
function toEnvelope(pos: OpenPosition): DataEnvelope {
  return {
    value: pos.current_price ?? null,
    source: pos.source ?? "unavailable",
    as_of: pos.as_of ?? null,
    is_live: pos.is_live ?? false,
    stale_after_s: pos.stale_after_s ?? DEFAULT_STALE_AFTER_S,
  };
}

interface PaperPositionsResponse {
  positions: OpenPosition[];
  count: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Maps action string to LONG / SHORT label. */
function getDirection(action: string): "LONG" | "SHORT" {
  const a = (action ?? "").toLowerCase();
  if (a === "buy" || a === "buy_to_open" || a === "buy_to_cover") return "LONG";
  return "SHORT";
}

/** Formats elapsed time from an ISO-8601 entry_time string to now. */
function formatTimeInTrade(entryTime: string): string {
  const entryMs = new Date(entryTime).getTime();
  if (isNaN(entryMs)) return "—";
  const diffMs = Date.now() - entryMs;
  if (diffMs < 0) return "—";
  const totalMins = Math.floor(diffMs / 60_000);
  if (totalMins < 60) return `${totalMins}m`;
  const hours = Math.floor(totalMins / 60);
  const mins = totalMins % 60;
  if (hours < 24) return `${hours}h ${mins}m`;
  const days = Math.floor(hours / 24);
  const remHours = hours % 24;
  return `${days}d ${remHours}h`;
}

/** Formats a dollar value with sign. */
function fmtPnl(val: number): string {
  const sign = val >= 0 ? "+" : "";
  return `${sign}$${Math.abs(val).toFixed(2)}`;
}

// ── Position row (own component so useProvenance can be called per-row) ────────

function PositionTableRow({ pos }: { pos: OpenPosition }) {
  const direction = getDirection(pos.action);
  const isLong = direction === "LONG";
  const pnl = pos.unrealized_pnl ?? null;
  // Mark provenance — the same envelope UnrealizedPnLWidget/WatchlistBar use,
  // so a stale/cached mark never shows a P&L number without a visible caveat.
  const markView = useProvenance(toEnvelope(pos));

  return (
    <tr className="border-t border-border">
      {/* Symbol */}
      <td className="py-2.5 pr-3">
        <span className="font-mono font-semibold text-foreground">
          {pos.symbol}
        </span>
      </td>

      {/* Direction */}
      <td className="py-2.5 pr-3">
        <Badge variant={isLong ? "bull" : "bear"}>
          {isLong ? (
            <TrendingUp className="inline h-3 w-3 mr-1" />
          ) : (
            <TrendingDown className="inline h-3 w-3 mr-1" />
          )}
          {direction}
        </Badge>
      </td>

      {/* Quantity / Contracts */}
      <td className="py-2.5 text-right font-mono tabular-nums text-foreground">
        {pos.quantity}
      </td>

      {/* Entry Price */}
      <td className="py-2.5 text-right font-mono tabular-nums text-foreground">
        ${pos.entry_price.toFixed(2)}
      </td>

      {/* Stop */}
      <td className="py-2.5 text-right font-mono tabular-nums text-destructive/80">
        {pos.stop_loss != null ? `$${pos.stop_loss.toFixed(2)}` : "—"}
      </td>

      {/* Target */}
      <td className="py-2.5 text-right font-mono tabular-nums text-bull/80">
        {pos.take_profit != null ? `$${pos.take_profit.toFixed(2)}` : "—"}
      </td>

      {/* Mark provenance — honest live/stale/static badge for current_price */}
      <td className="py-2.5 text-right">
        <ProvenanceBadge view={markView} />
      </td>

      {/* Unrealized P&L */}
      <td
        className={cn(
          "py-2.5 text-right font-mono tabular-nums font-semibold",
          pnl === null
            ? "text-muted-foreground"
            : pnl > 0
            ? "text-green-400"
            : pnl < 0
            ? "text-red-400"
            : "text-muted-foreground"
        )}
      >
        {pnl !== null ? fmtPnl(pnl) : "—"}
      </td>

      {/* Time in trade */}
      <td className="py-2.5 text-right font-mono tabular-nums text-muted-foreground text-xs">
        {pos.entry_time ? formatTimeInTrade(pos.entry_time) : "—"}
      </td>
    </tr>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function OpenPositionsWidget() {
  const [data, setData] = useState<PaperPositionsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const fetchPositions = useCallback(async () => {
    setRefreshing(true);
    try {
      const json = await fetchEngine<PaperPositionsResponse>("/portfolio/paper/positions");
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
    fetchPositions();
    const interval = setInterval(fetchPositions, 15_000);
    return () => clearInterval(interval);
  }, [fetchPositions]);

  const positions: OpenPosition[] = data?.positions ?? [];
  const count = data?.count ?? positions.length;
  const hasPositions = count > 0;
  const engineOffline = error !== null && data === null;

  // Compute total unrealized P&L across all open positions
  const totalUnrealizedPnl = positions.reduce(
    (sum, p) => sum + (p.unrealized_pnl ?? 0),
    0
  );

  return (
    <Card
      className={cn(
        "border-2 transition-colors",
        engineOffline
          ? "border-destructive/40"
          : hasPositions
          ? "border-warn/50 bg-warn/5"
          : "border-border"
      )}
    >
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <div className="flex items-center gap-2">
          <CardTitle className="text-base font-semibold tracking-tight">
            Open Positions
          </CardTitle>
          {/* 15s refresh indicator */}
          <span className="text-[10px] font-mono text-muted-foreground px-1.5 py-0.5 rounded border border-border">
            <RefreshCw
              className={cn("inline h-2.5 w-2.5 mr-1", refreshing && "animate-spin")}
            />
            15s
          </span>
        </div>

        <div className="flex items-center gap-2">
          {engineOffline && (
            <Badge variant="bear">
              <WifiOff className="inline h-3 w-3 mr-1" />
              Engine offline
            </Badge>
          )}
          {!engineOffline && hasPositions && (
            <Badge variant={totalUnrealizedPnl >= 0 ? "bull" : "bear"}>
              {fmtPnl(totalUnrealizedPnl)} Unrealized
            </Badge>
          )}
          {!engineOffline && !hasPositions && (
            <Badge variant="info">Flat</Badge>
          )}
          {!engineOffline && hasPositions && (
            <Badge variant="warn">{count} Open</Badge>
          )}
        </div>
      </CardHeader>

      <CardContent>
        {/* Engine offline error banner */}
        {engineOffline && (
          <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 mb-3 text-sm text-destructive">
            <WifiOff className="h-4 w-4 shrink-0" />
            <span>Engine offline — cannot retrieve positions: {error}</span>
          </div>
        )}

        {/* Non-fatal error (stale data still shown) */}
        {error && data !== null && (
          <p className="text-xs text-destructive mb-2">
            Warning: last refresh failed — {error}
          </p>
        )}

        {/* No open positions */}
        {!engineOffline && !hasPositions && (
          <div className="flex flex-col items-center justify-center py-8 gap-2">
            <span className="text-sm text-muted-foreground">No open positions</span>
            <Badge variant="info">Flat — no exposure</Badge>
          </div>
        )}

        {/* Positions table */}
        {!engineOffline && hasPositions && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  <th className="text-left pb-2 font-medium">Symbol</th>
                  <th className="text-left pb-2 font-medium">Direction</th>
                  <th className="text-right pb-2 font-medium">Qty</th>
                  <th className="text-right pb-2 font-medium">Entry</th>
                  <th className="text-right pb-2 font-medium">Stop</th>
                  <th className="text-right pb-2 font-medium">Target</th>
                  <th className="text-right pb-2 font-medium">Mark</th>
                  <th className="text-right pb-2 font-medium">Unreal. P&amp;L</th>
                  <th className="text-right pb-2 font-medium">Time In</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => (
                  <PositionTableRow
                    key={pos.trade_id ?? `${pos.symbol}-${pos.entry_time}`}
                    pos={pos}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Footer: last updated */}
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
