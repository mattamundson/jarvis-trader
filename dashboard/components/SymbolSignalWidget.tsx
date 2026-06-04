"use client";

import React, { useState, useEffect, useCallback } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface SignalData {
  symbol?: string;
  signal?: string;
  strength?: number;
  regime?: string;
  momentum?: string;
  atr?: number;
  current_price?: number;
  entry_price?: number;
  stop_price?: number;
  target_price?: number;
  timestamp?: string;
}

interface PipelineRun {
  id?: number;
  status?: string;
  signals_generated?: number;
  created_at?: string;
  completed_at?: string;
}

interface PipelineHistoryResponse {
  runs?: PipelineRun[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function relativeTime(isoStr: string): string {
  const diffMs = Date.now() - new Date(isoStr).getTime();
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  return `${diffHr}h ago`;
}

function signalBadgeVariant(signal?: string): "bull" | "bear" | "neutral" {
  if (signal === "LONG") return "bull";
  if (signal === "SHORT") return "bear";
  return "neutral";
}

function regimeBadgeVariant(regime?: string): "bull" | "bear" | "neutral" {
  if (!regime) return "neutral";
  const r = regime.toLowerCase();
  if (r === "bull" || r === "bullish") return "bull";
  if (r === "bear" || r === "bearish") return "bear";
  return "neutral";
}

function strengthColor(signal?: string): string {
  if (signal === "LONG") return "#22c55e"; // green
  if (signal === "SHORT") return "#ef4444"; // red
  return "#6b7280"; // gray
}

function formatPrice(price?: number): string {
  if (price == null) return "—";
  return price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function computeRR(entry?: number, stop?: number, target?: number): string | null {
  if (entry == null || stop == null || target == null) return null;
  const risk = Math.abs(entry - stop);
  const reward = Math.abs(target - entry);
  if (risk === 0) return null;
  const ratio = reward / risk;
  return `1:${ratio.toFixed(1)}`;
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function SignalCardSkeleton({ symbol }: { symbol: string }) {
  return (
    <div className="flex-1 min-w-0 rounded-lg border border-border bg-card p-4 space-y-3 animate-pulse">
      <div className="flex items-center justify-between">
        <div className="h-6 w-14 bg-muted rounded" />
        <div className="h-5 w-16 bg-muted rounded-full" />
      </div>
      <div className="h-1.5 bg-muted rounded-full" />
      <div className="space-y-2">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="flex justify-between">
            <div className="h-3 w-20 bg-muted rounded" />
            <div className="h-3 w-24 bg-muted rounded" />
          </div>
        ))}
      </div>
      <p className="text-[10px] text-muted-foreground">{symbol} signal loading…</p>
    </div>
  );
}

// ── Individual Signal Card ─────────────────────────────────────────────────────

interface SignalCardProps {
  label: string;
  data: SignalData | null;
  loading: boolean;
  error: boolean;
}

function SignalCard({ label, data, loading, error }: SignalCardProps) {
  if (loading) return <SignalCardSkeleton symbol={label} />;

  if (error || data == null) {
    return (
      <div className="flex-1 min-w-0 rounded-lg border border-border bg-card p-4 flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span className="text-lg font-bold text-foreground font-mono">{label}</span>
          <Badge variant="neutral">No signal</Badge>
        </div>
        <p className="text-xs text-muted-foreground">Signal unavailable</p>
      </div>
    );
  }

  const signal = data.signal ?? "FLAT";
  const strength = data.strength ?? 0;
  const rr = computeRR(data.entry_price, data.stop_price, data.target_price);

  return (
    <div className="flex-1 min-w-0 rounded-lg border border-border bg-card p-4 space-y-3">
      {/* Header row */}
      <div className="flex items-center justify-between gap-2">
        <span className="text-lg font-bold text-foreground font-mono">{data.symbol ?? label}</span>
        <Badge variant={signalBadgeVariant(signal)}>{signal}</Badge>
      </div>

      {/* Strength bar */}
      <div className="h-1.5 bg-muted rounded-full">
        <div
          style={{ width: `${Math.min(Math.max(strength, 0), 1) * 100}%`, backgroundColor: strengthColor(signal) }}
          className="h-1.5 rounded-full transition-all duration-500"
        />
      </div>

      {/* Regime + momentum row */}
      <div className="flex items-center gap-2 flex-wrap">
        {data.regime && (
          <Badge variant={regimeBadgeVariant(data.regime)}>
            {data.regime}
          </Badge>
        )}
        {data.momentum && (
          <Badge variant="info">{data.momentum}</Badge>
        )}
      </div>

      {/* Price info */}
      <div className="space-y-1.5">
        {data.current_price != null && (
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[11px] text-muted-foreground">Price</span>
            <span className="font-mono text-base font-semibold text-foreground tabular-nums">
              ${formatPrice(data.current_price)}
            </span>
          </div>
        )}
        {data.atr != null && (
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[11px] text-muted-foreground">ATR</span>
            <span className="font-mono text-xs text-muted-foreground tabular-nums">
              {data.atr.toFixed(1)} pts
            </span>
          </div>
        )}
        {data.entry_price != null && (
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[11px] text-muted-foreground">Entry</span>
            <span className="font-mono text-xs text-foreground tabular-nums">
              ${formatPrice(data.entry_price)}
            </span>
          </div>
        )}
        {data.stop_price != null && (
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[11px] text-muted-foreground">Stop</span>
            <span className="font-mono text-xs text-bear tabular-nums">
              ${formatPrice(data.stop_price)}
            </span>
          </div>
        )}
        {data.target_price != null && (
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[11px] text-muted-foreground">Target</span>
            <span className="font-mono text-xs text-bull tabular-nums">
              ${formatPrice(data.target_price)}
            </span>
          </div>
        )}
        {rr != null && (
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[11px] text-muted-foreground">R/R</span>
            <span className="font-mono text-xs text-info tabular-nums">{rr}</span>
          </div>
        )}
      </div>

      {/* Timestamp */}
      {data.timestamp && (
        <p className="text-[10px] text-muted-foreground">
          Updated {relativeTime(data.timestamp)}
        </p>
      )}
    </div>
  );
}

// ── Main Widget ────────────────────────────────────────────────────────────────
// Shows MCL (WFE=0.82) and MNQ (WFE=0.57) — the two approved paper instruments.
// Data sourced from /paper/runner-status which reads paper_runner.py live files.

export function SymbolSignalWidget() {
  const [mclData, setMclData] = useState<SignalData | null>(null);
  const [mclLoading, setMclLoading] = useState(true);
  const [mclError, setMclError] = useState(false);

  const [mnqData, setMnqData] = useState<SignalData | null>(null);
  const [mnqLoading, setMnqLoading] = useState(true);
  const [mnqError, setMnqError] = useState(false);

  const [pipelineRun, setPipelineRun] = useState<PipelineRun | null>(null);
  const [lastFetch, setLastFetch] = useState<Date | null>(null);
  const [tick, setTick] = useState(0);

  const fetchSignals = useCallback(async () => {
    // MCL + MNQ from paper runner status endpoint
    try {
      const json = await fetchEngine<Record<string, SignalData>>("/paper/runner-status");
      if (json.MCL) { setMclData(json.MCL); setMclError(false); }
      else { setMclData(null); }
      if (json.MNQ) { setMnqData(json.MNQ); setMnqError(false); }
      else { setMnqData(null); }
    } catch {
      setMclError(true);
      setMnqError(true);
      setMclData(null);
      setMnqData(null);
    } finally {
      setMclLoading(false);
      setMnqLoading(false);
    }

    // Pipeline history — handle 404 gracefully
    try {
      const json = await fetchEngine<PipelineHistoryResponse>("/pipeline/history?limit=1");
      const runs = json.runs ?? (Array.isArray(json) ? (json as PipelineRun[]) : []);
      setPipelineRun(runs[0] ?? null);
    } catch {
      setPipelineRun(null);
    }

    setLastFetch(new Date());
  }, []);

  // Initial fetch + 15-second interval
  useEffect(() => {
    fetchSignals();
    const id = setInterval(fetchSignals, 15_000);
    return () => clearInterval(id);
  }, [fetchSignals]);

  // Tick every second for relative time display
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1_000);
    return () => clearInterval(id);
  }, []);

  // Suppress unused variable warning for tick — it's used to force re-render
  void tick;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Signal Monitor</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Two signal cards side by side — MCL (WFE=0.82) and MNQ (WFE=0.57) */}
        <div className="flex gap-4 flex-col sm:flex-row">
          <SignalCard
            label="MCL"
            data={mclData}
            loading={mclLoading}
            error={mclError}
          />
          <SignalCard
            label="MNQ"
            data={mnqData}
            loading={mnqLoading}
            error={mnqError}
          />
        </div>

        {/* Last Pipeline Run */}
        <div className="rounded-lg border border-border bg-muted/30 px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-1.5">
            Last Pipeline Run
          </p>
          {pipelineRun ? (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-foreground">
              <span>
                Last run:{" "}
                <span className="font-mono text-muted-foreground">
                  {pipelineRun.created_at ? relativeTime(pipelineRun.created_at) : "—"}
                </span>
              </span>
              <span>
                Status:{" "}
                <Badge
                  variant={
                    pipelineRun.status === "COMPLETED"
                      ? "bull"
                      : pipelineRun.status === "FAILED"
                      ? "bear"
                      : "warn"
                  }
                >
                  {pipelineRun.status ?? "UNKNOWN"}
                </Badge>
              </span>
              <span>
                Signals generated:{" "}
                <span className="font-mono text-foreground">
                  {pipelineRun.signals_generated ?? 0}
                </span>
              </span>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">No pipeline runs found</p>
          )}
        </div>

        {/* Footer */}
        {lastFetch && (
          <p className="text-[10px] text-muted-foreground text-right">
            Refreshes every 15s · Last fetch: {relativeTime(lastFetch.toISOString())}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
