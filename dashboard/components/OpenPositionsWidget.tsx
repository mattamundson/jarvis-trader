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

const ENGINE_URL = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8010";

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
  // Live price fields (if engine enriches the response)
  current_price?: number | null;
  unrealized_pnl?: number | null;
}

interface PaperPositionsResponse {
  positions: OpenPosition[];
  count: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Maps action string to LONG / SHORT label. */
function getDirection(action: string): "LONG" | "SHORT" {
  const a = action.toLowerCase();
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

// ── Component ─────────────────────────────────────────────────────────────────

export function OpenPositionsWidget() {
  const [data, setData] = useState<PaperPositionsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const fetchPositions = useCallback(async () => {
    setRefreshing(true);
    try {
      const res = await fetch(`${ENGINE_URL}/portfolio/paper/positions`);
      if (!res.ok) throw new Error(`Engine returned HTTP ${res.status}`);
      const json = (await res.json()) as PaperPositionsResponse;
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
 