"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";

const ENGINE_URL = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8010";

const PAGE_SIZE = 10;

interface Trade {
  id?: string;
  symbol: string;
  side: string;
  entry_price?: number | null;
  exit_price?: number | null;
  realized_pnl?: number | null;
  entry_time?: string | null;
  exit_time?: string | null;
  status?: string;
}

type FilterType = "all" | "long" | "short";

function formatDuration(entry?: string | null, exit?: string | null): string {
  if (!entry || !exit) return "—";
  const diffMs = new Date(exit).getTime() - new Date(entry).getTime();
  if (isNaN(diffMs) || diffMs < 0) return "—";
  const totalMinutes = Math.floor(diffMs / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0) return `${minutes}m`;
  return minutes === 0 ? `${hours}h` : `${hours}h ${minutes}m`;
}

function formatPrice(price?: number | null): string {
  if (price == null) return "—";
  return `$${price.toFixed(2)}`;
}

function formatDate(exitTime?: string | null): string {
  if (!exitTime) return "—";
  const d = new Date(exitTime);
  if (isNaN(d.getTime())) return "—";
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const hours = String(d.getHours()).padStart(2, "0");
  const mins = String(d.getMinutes()).padStart(2, "0");
  return `${month}/${day} ${hours}:${mins}`;
}

function normalizeSide(side: string): "buy" | "sell" {
  const s = side.toLowerCase();
  if (s === "buy" || s === "long" || s === "buy_long") return "buy";
  return "sell";
}

export function RecentTradesTableWidget() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<boolean>(false);
  const [filter, setFilter] = useState<FilterType>("all");
  const [page, setPage] = useState<number>(0);

  const fetchTrades = async () => {
    try {
      const res = await fetch(
        `${ENGINE_URL}/portfolio/history/trades?status=CLOSED&limit=100`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: unknown = await res.json();
      const data: Trade[] = Array.isArray(json)
        ? (json as Trade[])
        : Array.isArray((json as { trades?: Trade[] }).trades)
        ? ((json as { trades: Trade[] }).trades as Trade[])
        : [];
      setTrades(data);
      setError(false);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTrades();
    const interval = setInterval(fetchTrades, 60_000);
    return () => clearInterval(interval);
  }, []);

  // Reset page when filter changes
  useEffect(() => {
    setPage(0);
  }, [filter]);

  const filtered = trades.filter((t) => {
    if (filter === "all") return true;
    const side = normalizeSide(t.side);
    if (filter === "long") return side === "buy";
    return side === "sell";
  });

  const totalCount = filtered.length;
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));
  const safePage = Math.min(page, totalPages - 1);
  const pageStart = safePage * PAGE_SIZE;
  const pageEnd = Math.min(pageStart + PAGE_SIZE, totalCount);
  const pageTrades = filtered.slice(pageStart, pageEnd);

  const showingFrom = totalCount === 0 ? 0 : pageStart + 1;
  const showingTo = pageEnd;

  const filterBtnClass = (f: FilterType) =>
    `px-3 py-1 rounded text-xs font-mono font-medium transition-colors ${
      filter === f
        ? "bg-white/10 text-white"
        : "text-muted-foreground hover:text-white"
    }`;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-base font-semibold">Recent Closed Trades</CardTitle>
        <div className="flex items-center gap-2">
          <button className={filterBtnClass("all")} onClick={() => setFilter("all")}>
            All
          </button>
          <button className={filterBtnClass("long")} onClick={() => setFilter("long")}>
            Long
          </button>
          <button className={filterBtnClass("short")} onClick={() => setFilter("short")}>
            Short
          </button>
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-8 rounded bg-muted animate-pulse"
              />
            ))}
          </div>
        ) : error ? (
          <p className="text-sm text-muted-foreground text-center py-6">
            Engine offline
          </p>
        ) : totalCount === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-6">
            No closed trades yet
          </p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground uppercase">
                    <th className="text-left pb-2">Symbol</th>
                    <th className="text-left pb-2">Side</th>
                    <th className="text-right pb-2">Entry</th>
                    <th className="text-right pb-2">Exit</th>
                    <th className="text-right pb-2">P&amp;L</th>
                    <th className="text-right pb-2">Duration</th>
                    <th className="text-right pb-2">Date</th>
                  </tr>
                </thead>
                <tbody>
                  {pageTrades.map((trade, i) => {
                    const side = normalizeSide(trade.side);
                    const pnl = trade.realized_pnl;
                    const pnlText =
                      pnl == null
                        ? "—"
                        : pnl >= 0
                        ? `+$${Math.abs(pnl).toFixed(2)}`
                        : `-$${Math.abs(pnl).toFixed(2)}`;
                    const pnlClass =
    