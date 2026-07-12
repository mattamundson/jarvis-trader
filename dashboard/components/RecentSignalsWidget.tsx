"use client";

import { useEffect, useState, useCallback } from "react";
import { AlertTriangle, Radio } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";


// ── Types ─────────────────────────────────────────────────────────────────────

type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

interface RecentSignal {
  id?: number;
  symbol?: string;
  action?: string;
  price?: number;
  timestamp?: string;
  source?: string;
  status?: string;
  result?: string;
}

interface RecentSignalsResponse {
  signals?: RecentSignal[];
  total?: number;
}

// ── Time helper ───────────────────────────────────────────────────────────────

function timeAgo(isoStr: string): string {
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// ── Badge helpers ─────────────────────────────────────────────────────────────

function actionVariant(action: string | undefined): BadgeVariant {
  const a = (action ?? "").toUpperCase();
  if (a === "LONG") return "bull";
  if (a === "SHORT") return "bear";
  if (a === "CLOSE") return "neutral";
  if (a === "HOLD") return "info";
  return "neutral";
}

function statusVariant(status: string | undefined): BadgeVariant {
  const s = (status ?? "").toLowerCase();
  if (s === "processed") return "bull";
  if (s === "rejected") return "bear";
  if (s === "pending") return "warn";
  if (s === "ignored") return "neutral";
  return "neutral";
}

// ── Skeleton rows ─────────────────────────────────────────────────────────────

function SkeletonRows() {
  return (
    <div className="space-y-2 animate-pulse">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="h-8 w-full rounded-lg bg-[#1a1a2e]" />
      ))}
    </div>
  );
}

// ── Main Widget ───────────────────────────────────────────────────────────────

export function RecentSignalsWidget() {
  const [data, setData] = useState<RecentSignalsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const payload = await fetchEngine(`/scanner/signals/latest?limit=10`, {
        cache: "no-store",
      });
      // Scanner route reports `count`; normalize to the widget's `total`.
      setData({ ...payload, total: payload?.total ?? payload?.count });
      setError(null);
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unavailable");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 30_000);
    return () => clearInterval(id);
  }, [fetchData]);

  const signals = data?.signals ?? [];
  const total = data?.total;

  return (
    <div className="rounded-xl border border-panel-border bg-panel p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Radio className="h-4 w-4 text-[#00ff88]" />
          <span className="font-mono text-[10px] font-bold tracking-[0.2em] uppercase text-[#00ff88]">
            {total != null
              ? `Recent Signals (${total} total)`
              : "Recent Signals"}
          </span>
          <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border border-[#00d4ff33] bg-[#00d4ff10] text-[#00d4ff]">
            AUTO-REFRESH 30s
          </span>
        </div>
        {lastUpdated && (
          <span className="font-mono text-[9px] text-[#333]">
            Updated: {lastUpdated}
          </span>
        )}
      </div>

      {/* Error banner */}
      {error && (
        <div className="rounded-lg px-3 py-2 font-mono text-xs flex items-center gap-2 bg-[#ff444410] border border-[#ff444430] text-[#ff8888]">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          Signals unavailable — {error}
        </div>
      )}

      {/* Loading skeleton */}
      {loading && <SkeletonRows />}

      {/* Empty state */}
      {!loading && !error && signals.length === 0 && (
        <div className="rounded-lg p-6 text-center bg-panel-alt">
          <span className="font-mono text-xs text-[#555]">
            No signals yet
          </span>
        </div>
      )}

      {/* Signal list */}
      {!loading && signals.length > 0 && (
        <div className="font-mono text-xs">
          {/* Table header */}
          <div className="grid grid-cols-5 gap-2 pb-2 mb-1 border-b border-panel-border">
            <span className="text-[10px] uppercase tracking-wider text-[#555]">
              Symbol
            </span>
            <span className="text-[10px] uppercase tracking-wider text-[#555]">
              Action
            </span>
            <span className="text-[10px] uppercase tracking-wider text-right text-[#555]">
              Price
            </span>
            <span className="text-[10px] uppercase tracking-wider text-right text-[#555]">
              Time
            </span>
            <span className="text-[10px] uppercase tracking-wider text-right text-[#555]">
              Status
            </span>
          </div>

          {/* Rows */}
          {signals.map((sig, idx) => (
            <div
              key={sig.id ?? idx}
              className="grid grid-cols-5 gap-2 py-1.5 items-center border-b border-[#111]"
            >
              {/* Symbol */}
              <span className="font-semibold text-[#e0e0e0]">
                {sig.symbol ?? "--"}
              </span>

              {/* Action badge */}
              <span>
                <Badge variant={actionVariant(sig.action)}>
                  {(sig.action ?? "--").toUpperCase()}
                </Badge>
              </span>

              {/* Price */}
              <span className="text-right tabular-nums text-[#e0e0e0]">
                {sig.price != null ? sig.price.toFixed(2) : "--"}
              </span>

              {/* Time */}
              <span className="text-right tabular-nums text-[#888]">
                {sig.timestamp ? timeAgo(sig.timestamp) : "--"}
              </span>

              {/* Status badge */}
              <span className="text-right">
                <Badge variant={statusVariant(sig.status)}>
                  {(sig.status ?? "--").toLowerCase()}
                </Badge>
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Provenance (P4.2): raw pre-pipeline scanner crossovers — flag the backend
          gap honestly rather than invent narrative reasoning. */}
      {!loading && !error && (
        <p className="font-mono text-[10px] leading-snug text-muted-foreground">
          Why: raw intraday STC crossovers from the scanner (pre-pipeline). No LLM
          reasoning is attached to these signals.
        </p>
      )}
    </div>
  );
}
