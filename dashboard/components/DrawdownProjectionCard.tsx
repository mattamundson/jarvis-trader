"use client";

import { useEffect, useState } from "react";
import { TrendingDown, AlertTriangle } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  EQUITY_CURVE_DAYS,
  PAPER_TRADES_LIMIT,
  PROJECTION_LOADING_COPY,
  PROJECTION_UNAVAILABLE_COPY,
  projectionCardState,
  type ClosedTradeRow,
  type EquityCurvePoint,
  type ReadyProjectionCard,
  type SafetyProjectionInput,
} from "@/lib/drawdownProjection";
import { POLL_INTERVAL } from "@/lib/polling-config";

/**
 * Drawdown Projection — Mission Control.
 *
 * Current drawdown and the halt come from GET /safety/status, the same
 * figures the kill switch uses. Average loss comes from
 * GET /portfolio/paper/performance. The peak line is the stored
 * daily_pnl.ending_balance from the equity-curve route that matches the
 * halt's implied peak. EQUITY_CURVE_DAYS builds that request.
 */

interface EquityCurveResponse {
  points?: Array<{ date?: string; equity?: number }>;
}

interface TradeHistoryResponse {
  trades?: ClosedTradeRow[];
}

function fmt(n: number | null | undefined, digits = 2): string {
  return n == null || !Number.isFinite(n) ? "—" : n.toFixed(digits);
}

function curvePoints(payload: EquityCurveResponse | null): EquityCurvePoint[] {
  const points = payload?.points ?? [];
  const out: EquityCurvePoint[] = [];
  for (const point of points) {
    const equity = Number(point?.equity);
    const date = point?.date ? String(point.date) : "";
    if (!date || !Number.isFinite(equity)) continue;
    out.push({ date, equity });
  }
  return out;
}

function cardShell(copy: string) {
  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-2">
      <div className="flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-warn" />
        <h3 className="text-sm font-semibold text-foreground">Drawdown Projection</h3>
      </div>
      <p className="text-xs text-muted-foreground">{copy}</p>
    </div>
  );
}

export function DrawdownProjectionCard() {
  const [proj, setProj] = useState<ReadyProjectionCard | null>(null);
  const [phase, setPhase] = useState<"loading" | "ready" | "unavailable">("loading");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [safety, wrapper, curve, tradesPayload] = await Promise.all([
          fetchEngine<SafetyProjectionInput>("/safety/status"),
          fetchEngine<Record<string, unknown>>("/portfolio/paper/performance"),
          fetchEngine<EquityCurveResponse>(
            `/portfolio/history/equity-curve?days=${EQUITY_CURVE_DAYS}`,
          ),
          fetchEngine<TradeHistoryResponse>(
            `/portfolio/paper/trades?status=closed&limit=${PAPER_TRADES_LIMIT}`,
          ),
        ]);
        if (cancelled) return;
        const perf = wrapper
          ? ((wrapper.performance as Record<string, unknown>) ?? wrapper)
          : null;
        const next = projectionCardState({
          failed: !safety || !wrapper,
          safety: safety ?? null,
          avgLossDollars: Number(perf?.avg_loss ?? 0),
          points: curvePoints(curve),
          trades: tradesPayload?.trades ?? [],
          asOf: new Date().toISOString().slice(0, 10),
        });
        if (next.status === "unavailable") {
          setProj(null);
          setPhase("unavailable");
          return;
        }
        setProj(next);
        setPhase("ready");
      } catch {
        if (!cancelled) {
          setPhase((current) => (current === "ready" ? current : "unavailable"));
        }
      }
    }

    load();
    const interval = setInterval(load, POLL_INTERVAL.SLOW);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  if (phase === "loading") return cardShell(PROJECTION_LOADING_COPY);
  if (phase !== "ready" || !proj) return cardShell(PROJECTION_UNAVAILABLE_COPY);

  const view = proj.projection;
  const critical = view.trades_remaining <= 3;
  const warning = view.trades_remaining <= 6 && !critical;
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

      <div className="grid grid-cols-2 gap-2 text-[10px]">
        <div>
          <span className="text-muted-foreground">Current DD</span>
          <div className="font-mono text-bear">{fmt(view.current_dd_pct)}%</div>
        </div>
        <div>
          <span className="text-muted-foreground">Halt</span>
          <div className="font-mono text-foreground">{fmt(view.max_drawdown_pct)}%</div>
        </div>
        <p className="col-span-2 font-mono text-[10px] text-muted-foreground">
          {proj.peakAudit}
        </p>
        {proj.detailLines.map((line, index) => (
          <p key={index} className="col-span-2 font-mono text-[10px] text-muted-foreground">
            {line}
          </p>
        ))}
        <div>
          <span className="text-muted-foreground">Avg Loss</span>
          <div className="font-mono text-bear">${fmt(view.avg_loss_dollars)}</div>
        </div>
        <div>
          <span className="text-muted-foreground">Equity</span>
          <div className="font-mono text-foreground">${fmt(view.portfolio_equity, 0)}</div>
        </div>
      </div>

      <div className="border-t border-border pt-2">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-muted-foreground flex items-center gap-1">
            <TrendingDown className="h-3 w-3" />
            Consecutive losses until halt
          </span>
          <span className={`font-mono font-semibold ${
            view.trades_remaining === Infinity
              ? "text-bull"
              : critical ? "text-bear" : "text-warn"
          }`}>
            {view.trades_remaining === Infinity ? "∞" : `${view.trades_remaining} trades`}
          </span>
        </div>

        {view.trades_remaining < Infinity && view.trades_remaining <= 8 && (
          <div className="mt-2 space-y-1">
            <div className="flex items-center gap-1">
              <span className="text-[8px] text-muted-foreground w-12 text-right">
                now
              </span>
              <div className="flex-1 h-3 bg-card rounded relative overflow-hidden border border-border">
                <div
                  className="absolute top-0 left-0 h-full bg-bear/20 rounded-l"
                  style={{ width: `${Math.min((view.current_dd_pct / view.max_drawdown_pct) * 100, 100)}%` }}
                />
                <div
                  className="absolute top-0 h-full w-0.5 bg-bear"
                  style={{ left: "100%" }}
                />
              </div>
              <span className="text-[8px] text-bear w-10">{fmt(view.max_drawdown_pct)}%</span>
            </div>
            {view.streak.map((eq, i) => {
              const ddAtStep = ((view.peak_equity - eq) / view.peak_equity) * 100;
              const barPct = Math.min((ddAtStep / view.max_drawdown_pct) * 100, 100);
              const stepVariant = ddAtStep >= view.max_drawdown_pct ? "bear" : "warn";
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
          Kill switch imminent — {view.trades_remaining} losing trades from halt.
          Reduce position size or pause trading.
        </p>
      )}
    </div>
  );
}
