"use client";

import { useEffect, useState } from "react";
import { Target, ShieldAlert, Minus, TrendingUp } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngineRaw } from "@/lib/api";
import { RawRecordBadge } from "@/components/RawRecordBadge";

// NOTE: outcome-bucketing (Target/Stopped/Partial/Scratch) requires an exit-reason
// or target/stop field that the deduped honest record does NOT carry. This widget
// intentionally keeps the raw /portfolio/history/trades source so it can bucket by
// inferred outcome. Trade COUNTS here may be inflated vs. the deduped record due
// to re-logged winners. A "Raw record · not deduped" badge makes this visible.

interface TradeRecord {
  id: number;
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  exit_price: number;
  realized_pnl: number;
  status: string;
  entry_time: string;
  exit_time: string | null;
  notes: string | null;
}

interface OutcomeStats {
  target: number;
  stopped: number;
  scratch: number;
  partial: number;
  avgTargetPnl: number;
  avgStopPnl: number;
  hitRate: number;
}

function classifyOutcome(pnl: number): "target" | "stopped" | "scratch" | "partial" {
  if (pnl > 50) return "target";
  if (pnl < -20) return "stopped";
  if (Math.abs(pnl) <= 20) return "scratch";
  return "partial";
}

function computeStats(trades: TradeRecord[]): OutcomeStats {
  let target = 0;
  let stopped = 0;
  let scratch = 0;
  let partial = 0;
  let targetPnlSum = 0;
  let stopPnlSum = 0;

  for (const t of trades) {
    const pnl = t.realized_pnl ?? 0;
    const outcome = classifyOutcome(pnl);
    if (outcome === "target") {
      target++;
      targetPnlSum += pnl;
    } else if (outcome === "stopped") {
      stopped++;
      stopPnlSum += pnl;
    } else if (outcome === "scratch") {
      scratch++;
    } else {
      partial++;
    }
  }

  const hitRate = target + stopped > 0 ? (target / (target + stopped)) * 100 : 0;
  const avgTargetPnl = target > 0 ? targetPnlSum / target : 0;
  const avgStopPnl = stopped > 0 ? stopPnlSum / stopped : 0;

  return { target, stopped, scratch, partial, avgTargetPnl, avgStopPnl, hitRate };
}

function qualityBadgeVariant(hitRate: number): "bull" | "warn" | "bear" {
  if (hitRate >= 50) return "bull";
  if (hitRate >= 35) return "warn";
  return "bear";
}

function qualityLabel(hitRate: number): string {
  if (hitRate >= 50) return "GOOD";
  if (hitRate >= 35) return "MARGINAL";
  return "POOR";
}

function fmt(n: number): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}$${n.toFixed(0)}`;
}

export function EntryQualityWidget() {
  const [stats, setStats] = useState<OutcomeStats | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    try {
      const res = await fetchEngineRaw(
        `/portfolio/history/trades?status=CLOSED&limit=200`,
        { cache: "no-store" }
      );
      const payload: unknown = await res.json();
      const rows: TradeRecord[] = Array.isArray(payload)
        ? payload
        : ((payload as { trades?: TradeRecord[] }).trades ?? []);
      const trades = rows.filter(
        (t: TradeRecord) =>
          t.realized_pnl !== null && t.realized_pnl !== undefined
      );
      setStats(computeStats(trades));
      setTotal(trades.length);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const interval = setInterval(load, 60000);
    return () => clearInterval(interval);
  }, []);

  const hitRate = stats?.hitRate ?? 0;
  const stopRate =
    stats && stats.target + stats.stopped > 0
      ? (stats.stopped / (stats.target + stats.stopped)) * 100
      : 0;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Entry Quality</CardTitle>
        <div className="flex items-center gap-2">
          {/* Prominent raw-data disclosure badge */}
          <RawRecordBadge className="text-[10px]" />
          {stats && !error && (
            <Badge variant={qualityBadgeVariant(hitRate)}>
              {qualityLabel(hitRate)} — {hitRate.toFixed(0)}% HIT RATE
            </Badge>
          )}
          {error && <Badge variant="bear">ERROR</Badge>}
          {loading && !stats && <Badge variant="neutral">LOADING…</Badge>}
        </div>
      </CardHeader>

      <CardContent>
        {error ? (
          <p className="font-mono text-xs" style={{ color: "#ff4444" }}>
            {error}
          </p>
        ) : loading && !stats ? (
          <p className="font-mono text-xs" style={{ color: "#555" }}>
            Loading trade history…
          </p>
        ) : stats ? (
          <div className="space-y-4">
            {/* Subtitle */}
            <p className="font-mono text-[10px]" style={{ color: "#555" }}>
              Based on {total} closed trade{total !== 1 ? "s" : ""} (raw, may include re-logged duplicates)
            </p>

            {/* 2x2 outcome grid */}
            <div className="grid grid-cols-2 gap-3">
              {/* Target Hit */}
              <div
                className="rounded-lg p-3"
                style={{ backgroundColor: "#001a0d", border: "1px solid #00ff8830" }}
              >
                <div className="flex items-center gap-1.5 mb-1">
                  <Target className="h-3.5 w-3.5" style={{ color: "#00ff88" }} />
                  <span
                    className="font-mono text-[10px] uppercase tracking-wider font-semibold"
                    style={{ color: "#00ff88" }}
                  >
                    Target Hit
                  </span>
                </div>
                <p
                  className="font-mono text-2xl font-bold tabular-nums"
                  style={{ color: "#00ff88" }}
                >
                  {stats.target}
                </p>
                {stats.target > 0 && (
                  <p className="font-mono text-[10px] tabular-nums mt-0.5" style={{ color: "#00cc66" }}>
                    avg {fmt(stats.avgTargetPnl)}
                  </p>
                )}
              </div>

              {/* Stopped */}
              <div
                className="rounded-lg p-3"
                style={{ backgroundColor: "#1a0000", border: "1px solid #ff444430" }}
              >
                <div className="flex items-center gap-1.5 mb-1">
                  <ShieldAlert className="h-3.5 w-3.5" style={{ color: "#ff4444" }} />
                  <span
                    className="font-mono text-[10px] uppercase tracking-wider font-semibold"
                    style={{ color: "#ff4444" }}
                  >
                    Stopped
                  </span>
                </div>
                <p
                  className="font-mono text-2xl font-bold tabular-nums"
                  style={{ color: "#ff4444" }}
                >
                  {stats.stopped}
                </p>
                {stats.stopped > 0 && (
                  <p className="font-mono text-[10px] tabular-nums mt-0.5" style={{ color: "#cc2222" }}>
                    avg {fmt(stats.avgStopPnl)}
                  </p>
                )}
              </div>

              {/* Partial Win */}
              <div
                className="rounded-lg p-3"
                style={{ backgroundColor: "#1a1400", border: "1px solid #ffcc0030" }}
              >
                <div className="flex items-center gap-1.5 mb-1">
                  <TrendingUp className="h-3.5 w-3.5" style={{ color: "#ffcc00" }} />
                  <span
                    className="font-mono text-[10px] uppercase tracking-wider font-semibold"
                    style={{ color: "#ffcc00" }}
                  >
                    Partial Win
                  </span>
                </div>
                <p
                  className="font-mono text-2xl font-bold tabular-nums"
                  style={{ color: "#ffcc00" }}
                >
                  {stats.partial}
                </p>
                <p className="font-mono text-[10px] mt-0.5" style={{ color: "#aa8800" }}>
                  $20 &lt; P&amp;L ≤ $50
                </p>
              </div>

              {/* Scratch */}
              <div
                className="rounded-lg p-3"
                style={{ backgroundColor: "#111", border: "1px solid #33333380" }}
              >
                <div className="flex items-center gap-1.5 mb-1">
                  <Minus className="h-3.5 w-3.5" style={{ color: "#888" }} />
                  <span
                    className="font-mono text-[10px] uppercase tracking-wider font-semibold"
                    style={{ color: "#888" }}
                  >
                    Scratch
                  </span>
                </div>
                <p
                  className="font-mono text-2xl font-bold tabular-nums"
                  style={{ color: "#888" }}
                >
                  {stats.scratch}
                </p>
                <p className="font-mono text-[10px] mt-0.5" style={{ color: "#555" }}>
                  |P&amp;L| ≤ $20
                </p>
              </div>
            </div>

            {/* Hit Rate vs Stop Rate comparison bar */}
            {(stats.target > 0 || stats.stopped > 0) && (
              <div>
                <div className="flex justify-between items-center mb-1">
                  <span className="font-mono text-[10px]" style={{ color: "#00ff88" }}>
                    Hit {hitRate.toFixed(0)}%
                  </span>
                  <span className="font-mono text-[10px]" style={{ color: "#ff4444" }}>
                    Stop {stopRate.toFixed(0)}%
                  </span>
                </div>
                <div
                  className="relative h-4 w-full overflow-hidden rounded"
                  style={{ backgroundColor: "#1a0000" }}
                >
                  <div
                    className="absolute top-0 left-0 h-full rounded-l transition-all duration-500"
                    style={{
                      width: `${hitRate}%`,
                      backgroundColor: "#00ff88",
                      opacity: 0.75,
                    }}
                  />
                </div>
              </div>
            )}

            {/* Classification + data-quality note */}
            <p className="font-mono text-[9px]" style={{ color: "#444" }}>
              Target: &gt;$50 | Stop: &lt;-$20 | Scratch: |P&amp;L|≤$20 | Outcome inferred from P&amp;L only (no exit-reason in deduped record) | Refreshes every 60s
            </p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
