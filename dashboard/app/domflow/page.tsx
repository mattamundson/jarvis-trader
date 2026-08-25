"use client";

import { useMemo } from "react";
import useSWR from "swr";
import { Badge } from "@/components/ui/badge";
import { fetchDomflow, type DomflowHistoryResponse, type DomflowSnapshot } from "@/lib/api";
import { ServerOff } from "lucide-react";

const POLL_MS = 10_000; // spec: live gauge polls every 5-10s

function formatAge(ageSeconds: number | null): string {
  if (ageSeconds === null) return "—";
  if (ageSeconds < 60) return `${Math.round(ageSeconds)}s`;
  return `${Math.round(ageSeconds / 60)}m`;
}

function fmtTs(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString(undefined, { hour12: false });
  } catch {
    return ts;
  }
}

function ImbalanceGauge({ ratio }: { ratio: number }) {
  // Horizontal bar centered at 0.5 — bid pressure to the right, ask to the left.
  const pct = Math.min(100, Math.max(0, ratio * 100));
  const bidPct = Math.min(50, pct); // right half shows bid share above 0.5
  const askPct = Math.min(50, 100 - pct); // left half shows ask share below 0.5
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-slate-400">
        <span>Ask-heavy</span>
        <span className="font-mono">{ratio.toFixed(3)}</span>
        <span>Bid-heavy</span>
      </div>
      <div className="relative h-3 w-full overflow-hidden rounded bg-slate-800">
        {/* Ask side (left of center) */}
        <div
          className="absolute left-0 top-0 h-full bg-bear/60"
          style={{ width: `${askPct}%` }}
          title={`ask_volume ${(1 - ratio).toFixed(3)}`}
        />
        {/* Bid side (right of center) */}
        <div
          className="absolute right-0 top-0 h-full bg-bull/60"
          style={{ width: `${bidPct}%` }}
          title={`bid_volume ${ratio.toFixed(3)}`}
        />
        {/* Center marker */}
        <div className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-slate-400" />
      </div>
    </div>
  );
}

export default function DomflowPage() {
  const { data: latest, error: latestError, isLoading: latestLoading } = useSWR<DomflowSnapshot>(
    ["domflow", "latest"],
    () => fetchDomflow<DomflowSnapshot>("/domflow/mes/latest"),
    { refreshInterval: POLL_MS, revalidateOnFocus: false },
  );

  const { data: history } = useSWR<DomflowHistoryResponse>(
    ["domflow", "history", 60],
    () => fetchDomflow<DomflowHistoryResponse>("/domflow/mes/history?minutes=60"),
    { refreshInterval: POLL_MS * 6, revalidateOnFocus: false },
  );

  const spark = useMemo(() => {
    if (!history?.snapshots?.length) return null;
    const pts = history.snapshots
      .filter((s) => s && typeof s.imbalance_ratio === "number")
      .slice(-60);
    if (!pts.length) return null;
    const max = Math.max(...pts.map((p) => p.imbalance_ratio));
    const min = Math.min(...pts.map((p) => p.imbalance_ratio));
    const span = max - min || 1;
    return { pts, max, min, span };
  }, [history]);

  const label =
    latest && typeof latest.imbalance_ratio === "number"
      ? latest.imbalance_ratio > 0.6
        ? "bull"
        : latest.imbalance_ratio < 0.4
          ? "bear"
          : "neutral"
      : "neutral";

  const tierBadge = latest?.depth_tier === "L2" ? "live" : latest?.stale ? "static" : "info";
  const tierText =
    latest?.depth_tier === "L2"
      ? "L2 depth"
      : latest?.depth_tier === "L1_DELAYED"
        ? "L1 top-of-book (delayed)"
        : "no data";

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">MES DOM / Order-Flow</h1>
        <Badge variant={label}>{label}</Badge>
        <Badge variant={tierBadge}>{tierText}</Badge>
        {latest?.stale && <Badge variant="warn">stale {formatAge(latest.age_seconds)}</Badge>}
        {!latest?.connected && !latest?.stale && <Badge variant="warn">disconnected</Badge>}
      </div>

      <p className="max-w-2xl text-xs text-slate-400">
        Order-flow imbalance = bid_volume / (bid_volume + ask_volume). &gt;0.6 bull, &lt;0.4
        bear. Phase 1 is read-only and informational — this signal is NOT fed into the trading
        pipeline (Phase 2, forward-graded only). Depth tier is tagged honestly: the paper
        account has no L2 depth subscription, so IBKR delivers delayed top-of-book (L1) and the
        service labels it as such.
      </p>

      {latestLoading && !latest && <div className="text-sm text-slate-500">Loading…</div>}
      {latestError && !latest && (
        <div className="rounded-xl border border-warn/30 bg-warn/5 p-6 text-center space-y-2">
          <ServerOff className="h-8 w-8 text-warn mx-auto" />
          <p className="text-sm font-semibold text-warn">DOM flow module not provisioned</p>
          <p className="text-xs text-muted-foreground max-w-2xl mx-auto">
            The DOM flow service is not running — the proxy could not reach it
            ({latestError instanceof Error ? latestError.message : "unknown error"}). This is a
            disabled module, not a data gap: no order-flow snapshots are being collected, so there
            is nothing to show. Start the isolated domflow service (or provision its feed key) to
            enable this page.
          </p>
        </div>
      )}

      {latestError && latest && (
        <div className="text-sm text-bear">
          domflow proxy error: {latestError instanceof Error ? latestError.message : "unknown"}
        </div>
      )}

      {latest && (
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded border border-border bg-card p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-medium">Imbalance Ratio</span>
              <span className="font-mono text-xs text-slate-400">
                {fmtTs(latest.ts_utc)} · age {formatAge(latest.age_seconds)}
              </span>
            </div>
            <ImbalanceGauge ratio={latest.imbalance_ratio} />
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
              <div>
                <div className="text-slate-400">Bid vol (top5)</div>
                <div className="font-mono text-bull">{latest.bid_volume_top5}</div>
              </div>
              <div>
                <div className="text-slate-400">Ask vol (top5)</div>
                <div className="font-mono text-bear">{latest.ask_volume_top5}</div>
              </div>
            </div>
          </div>

          <div className="rounded border border-border bg-card p-4">
            <div className="mb-2 text-sm font-medium">Book</div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 font-mono text-xs">
              <div className="text-slate-400">Bid</div>
              <div className="text-slate-400">Ask</div>
              <div className="text-bull">{latest.best_bid ?? "—"}</div>
              <div className="text-bear">{latest.best_ask ?? "—"}</div>
              <div className="text-slate-400">Mid</div>
              <div className="text-slate-400">Spread</div>
              <div>{latest.mid_price ?? "—"}</div>
              <div>{latest.spread ?? "—"}</div>
            </div>
          </div>
        </div>
      )}

      <div className="rounded border border-border bg-card p-4">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-medium">Imbalance — last 60m</span>
          <span className="text-xs text-slate-400">
            {history?.count ?? 0} snapshots · every 10s
          </span>
        </div>
        {spark ? (
          <div className="flex h-20 items-end gap-px">
            {spark.pts.map((p, i) => (
              <div
                key={i}
                className={p.imbalance_ratio > 0.6 ? "bg-bull/70" : p.imbalance_ratio < 0.4 ? "bg-bear/70" : "bg-slate-500/70"}
                style={{ height: `${((p.imbalance_ratio - spark.min) / spark.span) * 100}%` }}
                title={`${fmtTs(p.ts_utc)} ratio ${p.imbalance_ratio.toFixed(3)}`}
              />
            ))}
          </div>
        ) : (
          <div className="text-xs text-slate-500">No history yet — snapshots persist every 10s once the service is subscribed.</div>
        )}
      </div>
    </div>
  );
}
