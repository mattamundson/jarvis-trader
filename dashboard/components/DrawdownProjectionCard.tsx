"use client";

import { useEffect, useState } from "react";
import { TrendingDown, AlertTriangle } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { POLL_INTERVAL } from "@/lib/polling-config";

/**
 * Drawdown Projection — Mission Control.
 *
 * Shows exactly how many consecutive losing trades remain before the kill
 * switch fires at -20% drawdown.  Computed from:
 *   - Current drawdown %       (GET /portfolio/paper/performance)
 *   - Average loss per trade   (derived from the performance data)
 *   - Portfolio equity         (same endpoint)
 *
 * The projection is mechanical (not a model): it answers "if every
 * future trade loses the same amount as the average loser, how many
 * losing trades until the kill switch halts everything?"
 *
 * The card also shows the trajectory visually: each projected loss is a
 * step toward the red kill-switch line.
 */

interface Projection {
  current_dd_pct: number;
  avg_loss_dollars: number;
  portfolio_equity: number;
  max_drawdown_pct: number;
  trades_remaining: number;   // how many avg losses until halt
  streak: number[];           // projected equity after each loss
}

function fmt(n: number | null | undefined, digits = 2): string {
  return n == null || !Number.isFinite(n) ? "—" : n.toFixed(digits);
}

export function DrawdownProjectionCard() {
  const [proj, setProj] = useState<Projection | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const wrapper = await fetchEngine<Record<string, unknown>>(
          "/portfolio/paper/performance"
        );
        if (cancelled || !wrapper) return;

        // Real shape: { performance: { total_pnl, avg_loss (NEGATIVE),
        // max_dd (DOLLARS, negative), win_rate, profit_factor, num_trades } }.
        // Drawdown % must be derived against peak equity — the route has no
        // drawdown_pct field.
        const perf = (wrapper.performance as Record<string, unknown>) ?? wrapper;
        const totalPnl = Number(perf.total_pnl ?? 0);
        const maxDdDollars = Math.abs(Number(perf.max_dd ?? 0));
        const avgLossRaw = Number(perf.avg_loss ?? 0);
        const avgLoss = Math.abs(avgLossRaw); // route reports it negative

        const STARTING_EQUITY = 10000;
        const equity = STARTING_EQUITY + totalPnl;
        const peakEquity = equity + maxDdDollars;
        const ddPct = peakEquity > 0 ? (maxDdDollars / peakEquity) * 100 : 0;

        const maxDD = Number(perf.max_drawdown_pct ?? 20);

        // Projection: how many avg-loss trades until the kill switch
        const remaining = ((maxDD - ddPct) / 100) * equity;
        const tradesLeft = avgLoss > 0
          ? Math.max(0, Math.floor(remaining / avgLoss))
          : Infinity;

        const streak: number[] = [];
        let projected = equity;
        for (let i = 0; i < Math.min(tradesLeft, 8); i++) {
          projected -= avgLoss > 0 ? avgLoss : 0;
          streak.push(projected);
        }

        setProj({
          current_dd_pct: ddPct,
          avg_loss_dollars: avgLoss,
          portfolio_equity: equity,
          max_drawdown_pct: maxDD,
          trades_remaining: tradesLeft,
          streak,
        });
      } catch {
        // data unavailable — card stays in loading/empty state
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    const interval = setInterval(load, POLL_INTERVAL.SLOW);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  if (loading || !proj) {
    return (
      <div className="rounded-lg border border-border bg-card p-4 space-y-2">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-warn" />
          <h3 className="text-sm font-semibold text-foreground">Drawdown Projection</h3>
        </div>
        <p className="text-xs text-muted-foreground">Loading projection…</p>
      </div>
    );
  }

  const critical = proj.trades_remaining <= 3;
  const warning = proj.trades_remaining <= 6 && !critical;
  const variant: "bear" | "warn" | "neutral" = critical ? "bear" : warning ? "warn" : "neutral";

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <AlertTriangle className={`h-4 w-4 ${critical ? "text-bear" : "text-warn"}`} />
        <h3 className="text-sm font-semibold text-foreground">Drawdown Projection</h3>
        <Badge variant={variant} className="ml-auto text-[10px]">
          {critical ? "CRITICAL" : warning ? "WARNING" : "OK"}
        </Badge>
      </div>

      {/* Key metrics */}
      <div className="grid grid-cols-2 gap-2 text-[10px]">
        <div>
          <span className="text-muted-foreground">Current DD</span>
          <div className="font-mono text-bear">{fmt(proj.current_dd_pct)}%</div>
        </div>
        <div>
          <span className="text-muted-foreground">Max DD</span>
          <div className="font-mono text-foreground">{fmt(proj.max_drawdown_pct)}%</div>
        </div>
        <div>
          <span className="text-muted-foreground">Avg Loss</span>
          <div className="font-mono text-bear">${fmt(proj.avg_loss_dollars)}</div>
        </div>
        <div>
          <span className="text-muted-foreground">Equity</span>
          <div className="font-mono text-foreground">${fmt(proj.portfolio_equity, 0)}</div>
        </div>
      </div>

      {/* Projection */}
      <div className="border-t border-border pt-2">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-muted-foreground flex items-center gap-1">
            <TrendingDown className="h-3 w-3" />
            Consecutive losses until halt
          </span>
          <span className={`font-mono font-semibold ${
            proj.trades_remaining === Infinity
              ? "text-bull"
              : critical ? "text-bear" : "text-warn"
          }`}>
            {proj.trades_remaining === Infinity ? "∞" : `${proj.trades_remaining} trades`}
          </span>
        </div>

        {/* Visual bar: each projected loss */}
        {proj.trades_remaining < Infinity && proj.trades_remaining <= 8 && (
          <div className="mt-2 space-y-1">
            <div className="flex items-center gap-1">
              {/* Current equity marker */}
              <span className="text-[8px] text-muted-foreground w-12 text-right">
                now
              </span>
              <div className="flex-1 h-3 bg-card rounded relative overflow-hidden border border-border">
                {/* Fill from 0 to current dd position */}
                <div
                  className="absolute top-0 left-0 h-full bg-bear/20 rounded-l"
                  style={{ width: `${Math.min((proj.current_dd_pct / proj.max_drawdown_pct) * 100, 100)}%` }}
                />
                {/* Kill switch line */}
                <div
                  className="absolute top-0 h-full w-0.5 bg-bear"
                  style={{ left: "100%" }}
                />
              </div>
              <span className="text-[8px] text-bear w-10">{fmt(proj.max_drawdown_pct)}%</span>
            </div>
            {proj.streak.map((eq, i) => {
              const ddAtStep = ((proj.portfolio_equity - eq) / proj.portfolio_equity) * 100;
              const barPct = Math.min((ddAtStep / proj.max_drawdown_pct) * 100, 100);
              const stepVariant = ddAtStep >= proj.max_drawdown_pct ? "bear" : "warn";
              return (
                <div key={i} className="flex items-center gap-1">
                  <span className="text-[8px] text-muted-foreground w-12 text-right">
                    -{i + 1}
                  </span>
                  <div className="flex-1 h-2 bg-card rounded relative overflow-hidden border border-border">
                    <div
                      className={`absolute top-0 left-0 h-full rounded-l ${
                        stepVariant === "bear" ? "bg-bear/40" : "bg-warn/30"
                      }`}
                      style={{ width: `${barPct}%` }}
                    />
                  </div>
                  <span className={`text-[8px] font-mono ${
                    stepVariant === "bear" ? "text-bear" : "text-warn"
                  } w-10`}>
                    {fmt(ddAtStep)}%
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {critical && (
        <p className="text-[10px] text-bear border-t border-border pt-2">
          Kill switch imminent — {proj.trades_remaining} losing trades from halt.
          Reduce position size or pause trading.
        </p>
      )}
    </div>
  );
}