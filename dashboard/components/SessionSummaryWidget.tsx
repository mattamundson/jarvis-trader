"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CalendarDays } from "lucide-react";

const ENGINE_URL =
  process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8010";

interface SessionStats {
  date: string;
  trades_today: number;
  pnl_today: number;
  wins_today: number;
  losses_today: number;
  win_rate_today: number;
  open_positions: number;
  session: string;
}

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr + "T00:00:00");
    return d.toLocaleDateString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return dateStr;
  }
}

function formatPnl(pnl: number): string {
  const sign = pnl >= 0 ? "+" : "";
  return `${sign}$${pnl.toFixed(2)}`;
}

export function SessionSummaryWidget() {
  const [data, setData] = useState<SessionStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch(
          `${ENGINE_URL}/portfolio/stats/session-today`,
          { cache: "no-store" }
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json: SessionStats = await res.json();
        setData(json);
        setError(false);
      } catch {
        setError(true);
        setData(null);
      } finally {
        setLoading(false);
      }
    };

    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, []);

  // ── Skeleton ────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2">
            <CalendarDays className="h-4 w-4" />
            Session Summary
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="animate-pulse space-y-2">
            <div className="h-8 w-32 bg-muted rounded" />
            <div className="grid grid-cols-4 gap-3">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-10 bg-muted rounded" />
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  // ── Error / no data ─────────────────────────────────────────────────────────
  if (error || !data) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2">
            <CalendarDays className="h-4 w-4" />
            Session Summary
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Session data unavailable
          </p>
        </CardContent>
      </Card>
    );
  }

  // ── Derived badge variants ──────────────────────────────────────────────────
  const pnlVariant: "bull" | "bear" | "neutral" =
    data.pnl_today > 0 ? "bull" : data.pnl_today < 0 ? "bear" : "neutral";

  const sessionVariant: "bull" | "neutral" =
    data.session === "RTH" ? "bull" : "neutral";

  // ── Full render ─────────────────────────────────────────────────────────────
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <CardTitle className="flex items-center gap-2">
            <CalendarDays className="h-4 w-4" />
            Session Summary
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant={sessionVariant}>{data.session || "—"}</Badge>
            <span className="text-xs text-muted-foreground">
              {formatDate(data.date)}
            </span>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        <div className="flex flex-wrap items-center gap-6">
          {/* P&L — large, colored */}
          <div className="flex flex-col gap-0.5 min-w-[90px]">
            <span className="text-xs text-muted-foreground uppercase tracking-wide">
              P&amp;L Today
            </span>
            <span
              className={`text-2xl font-bold font-mono ${
                pnlVariant === "bull"
                  ? "text-bull"
                  : pnlVariant === "bear"
                  ? "text-bear"
                  : "text-muted-foreground"
              }`}
            >
              {formatPnl(data.pnl_today)}
            </span>
          </div>

          <div className="h-10 w-px bg-border hidden sm:block" />

          {/* Trades */}
          <div className="flex flex-col gap-0.5">
            <span className="text-xs text-muted-foreground uppercase tracking-wide">
              Trades
            </span>
            <span className="text-lg font-semibold font-mono text-foreground">
              {data.trades_today ?? "—"}
            </span>
          </div>

          {/* Win / Loss */}
          <div className="flex flex-col gap-0.5">
            <span className="text-xs text-muted-foreground uppercase tracking-wide">
              W / L
            </span>
            <span className="text-lg font-semibold font-mono">
              <span className="text-bull">{data.wins_today ?? "—"}</span>
              <span className="text-muted-foreground"> / </span>
              <span className="text-bear">{data.losses_today ?? "—"}</span>
            </span>
          </div>

          {/* Win Rate */}
          <div className="flex flex-col gap-0.5">
            <span className="text-xs text-muted-foreground uppercase tracking-wide">
              Win Rate
            </span>
            <span className="text-lg font-semibold font-mono text-foreground">
              {data.win_rate_today != null
                ? `${data.win_rate_today.toFixed(1)}%`
                : "—"}
            </span>
          </div>

          {/* Open Positions */}
          <div className="flex flex-col gap-0.5">
            <span className="text-xs text-muted-foreground uppercase tracking-wide">
              Open Positions
            </span>
            <div className="flex items-center gap-1.5">
              <span className="text-lg font-semibold font-mono text-foreground">
                {data.open_positions ?? "—"}
              </span>
              {data.open_positions > 0 && (
                <Badge variant="warn">{data.open_positions} open</Badge>
              )}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
