"use client";

import React, { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";

const ENGINE_URL = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8010";

// ── Types ─────────────────────────────────────────────────────────────────────

interface TradeRecord {
  id: number;
  symbol: string;
  side: "BUY" | "SELL";
  realized_pnl: number | null;
  status: string;
  entry_time: string;
  exit_time: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtCurrency(value: number): string {
  const abs = Math.abs(value);
  const formatted = abs.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
  return `${value < 0 ? "-" : ""}$${formatted}`;
}

function fmtCurrencyFull(value: number): string {
  const abs = Math.abs(value);
  const formatted = abs.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${value < 0 ? "-" : ""}$${formatted}`;
}

// ── Chart constants ───────────────────────────────────────────────────────────

const VB_W = 600;
const VB_H = 200;
const PAD_LEFT = 50;
const PAD_RIGHT = 20;
const PAD_TOP = 20;
const PAD_BOTTOM = 30;

const PLOT_W = VB_W - PAD_LEFT - PAD_RIGHT;
const PLOT_H = VB_H - PAD_TOP - PAD_BOTTOM;

// ── Component ─────────────────────────────────────────────────────────────────

export function EquityCurveWidget() {
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function fetchTrades() {
    try {
      setError(null);
      const res = await fetch(
        `${ENGINE_URL}/portfolio/history/trades?status=CLOSED&limit=500`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw: unknown = await res.json();

      let list: TradeRecord[];
      if (Array.isArray(raw)) {
        list = raw as TradeRecord[];
      } else if (
        raw !== null &&
        typeof raw === "object" &&
        "trades" in raw &&
        Array.isArray((raw as { trades: unknown }).trades)
      ) {
        list = (raw as { trades: TradeRecord[] }).trades;
      } else {
        list = [];
      }

      // Sort by exit_time ascending, keep only trades with an exit_time
      const closed = list
        .filter((t) => t.exit_time !== null && t.exit_time !== undefined)
        .sort((a, b) => {
          const ta = new Date(a.exit_time as string).getTime();
          const tb = new Date(b.exit_time as string).getTime();
          return ta - tb;
        });

      setTrades(closed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchTrades();
    const id = setInterval(fetchTrades, 120_000);
    return () => clearInterval(id);
  }, []);

  // ── Derived data ──────────────────────────────────────────────────────────

  // Running cumulative P&L starting at $0
  const cumulative: number[] = [];
  let running = 0;
  for (const t of trades) {
    running += t.realized_pnl ?? 0;
    cumulative.push(running);
  }

  const totalPnl = cumulative.length > 0 ? cumulative[cumulative.length - 1] : 0;
  const peakPnl = cumulative.length > 0 ? Math.max(...cumulative) : 0;
  const fromPeak = totalPnl - peakPnl;

  const minCum = cumulative.length > 0 ? Math.min(0, ...cumulative) : 0;
  const maxCum = cumulative.length > 0 ? Math.max(0, ...cumulative) : 0;

  // Badge
  let badgeVariant: "bull" | "bear" | "neutral";
  let badgeLabel: string;
  if (totalPnl > 0) {
    badgeVariant = "bull";
    badgeLabel = "PROFITABLE";
  } else if (totalPnl < 0) {
    badgeVariant = "bear";
    badgeLabel = "IN DRAWDOWN";
  } else {
    badgeVariant = "neutral";
    badgeLabel = "FLAT";
  }

  // Colors
  const isPositive = totalPnl >= 0;
  const strokeColor = isPositive ? "#22c55e" : "#ef4444";
  const fillColor = isPositive
    ? "rgba(34,197,94,0.15)"
    : "rgba(239,68,68,0.15)";
  const endDotColor = isPositive ? "#22c55e" : "#ef4444";

  // ── SVG coordinate helpers ────────────────────────────────────────────────

  function toX(index: number, total: number): number {
    if (total <= 1) return PAD_LEFT + PLOT_W / 2;
    return PAD_LEFT + (index / (total - 1)) * PLOT_W;
  }

  function toY(val: number): number {
    const range = maxCum - minCum || 1;
    return PAD_TOP + PLOT_H - ((val - minCum) / range) * PLOT_H;
  }

  // Zero-line Y
  const zeroY = toY(0);

  // Build chart SVG contents
  function buildChart(): React.ReactNode {
    const n = cumulative.length;
    if (n === 0) return null;

    // For single trade, just draw a dot
    if (n === 1) {
      const cx = toX(0, 1);
      const cy = toY(cumulative[0]);
      return (
        <>
          {/* Zero baseline */}
          <line
            x1={PAD_LEFT}
            y1={zeroY}
            x2={VB_W - PAD_RIGHT}
            y2={zeroY}
            stroke="#666"
            strokeDasharray="4,4"
            strokeWidth="1"
          />
          <circle cx={cx} cy={cy} r={5} fill={endDotColor} />
        </>
      );
    }

    // Build point array
    const points = cumulative.map((v, i) => ({
      x: toX(i, n),
      y: toY(v),
    }));

    // Line path
    const linePath = points
      .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
      .join(" ");