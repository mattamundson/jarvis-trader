"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import {
  Activity,
  CheckCircle2,
  Clock,
  Database,
  RefreshCw,
  Server,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface DataSource {
  source: string;
  last_update: string;
  latency_sec: number;
  status: "healthy" | "stale";
}

interface DataIntegrityResponse {
  timestamp: string;
  sources: DataSource[];
  count: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

function formatLatency(seconds: number): string {
  if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
  return `${seconds.toFixed(1)}s`;
}

// ── Page Component ────────────────────────────────────────────────────────────

export default function DataIntegrityPage() {
  const { data, error, mutate, isLoading } = useSWR<DataIntegrityResponse>(
    "/system/data-integrity",
    fetcher,
    { refreshInterval: 2000 }
  );

  return (
    <div className="flex flex-col gap-8 p-8 max-w-6xl mx-auto">
      <div className="flex items-center justify-between border-b pb-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Data Integrity</h1>
          <p className="text-muted-foreground mt-1">
            Real-time monitoring of the JARVIS Data Fabric (Phase 2.1 - 2.5)
          </p>
        </div>
        <div className="flex items-center gap-4">
          <Badge variant={data?.count ? "info" : "bear"}>
            {data?.count || 0} active streams
          </Badge>
          <button
            onClick={() => mutate()}
            className="p-2 hover:bg-secondary rounded-full transition-colors"
            title="Refresh now"
          >
            <RefreshCw className={`w-5 h-5 ${isLoading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-destructive/10 border border-destructive text-destructive rounded-lg">
          Failed to fetch data integrity metrics: {error.message}
        </div>
      )}

      {isLoading && !data && (
        <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
          <RefreshCw className="w-4 h-4 animate-spin mr-2" /> Loading data-integrity metrics…
        </div>
      )}

      {data && (data.sources?.length ?? 0) === 0 && !error && (
        <div className="p-6 border border-border rounded-xl text-center text-sm text-muted-foreground">
          No data sources reported by the engine.
        </div>
      )}

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {(data?.sources ?? []).map((src) => (
          <div
            key={src.source}
            className={`p-6 border rounded-xl shadow-sm transition-all bg-card ${
              src.status === "healthy" ? "border-green-500/20" : "border-amber-500/20"
            }`}
          >
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className={`p-2 rounded-lg ${
                  src.status === "healthy" ? "bg-green-500/10 text-green-500" : "bg-amber-500/10 text-amber-500"
                }`}>
                  <Zap className="w-5 h-5" />
                </div>
                <h3 className="font-semibold uppercase tracking-wider text-sm">{src.source}</h3>
              </div>
              <Badge variant={src.status === "healthy" ? "bull" : "warn"}>
                {src.status}
              </Badge>
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground flex items-center gap-2">
                  <Clock className="w-4 h-4" /> Latency
                </span>
                <span className={`font-mono font-medium ${src.latency_sec > 5 ? "text-amber-500" : ""}`}>
                  {formatLatency(src.latency_sec)}
                </span>
              </div>
              
              <div className="flex items-center justify-between text-sm border-t pt-3">
                <span className="text-muted-foreground flex items-center gap-2">
                  <Activity className="w-4 h-4" /> Last Update
                </span>
                <span className="font-mono text-xs opacity-80">
                  {new Date(src.last_update).toLocaleTimeString()}
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <div className="p-6 border rounded-xl bg-card">
          <div className="flex items-center gap-3 mb-2">
            <Server className="w-6 h-6 text-primary" />
            <h2 className="text-xl font-semibold">Infrastructure Status</h2>
          </div>
          <p className="text-[11px] text-muted-foreground italic mb-4">
            Configured endpoints (not live-probed here) — see{" "}
            <a href="/health" className="text-blue-400 underline">/health</a> for live subsystem state.
          </p>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm">Redis Pub/Sub</span>
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-slate-500" />
                <span className="text-sm font-medium text-muted-foreground">CONFIGURED</span>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm">QuestDB ILP (port 9009)</span>
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-slate-500" />
                <span className="text-sm font-medium text-muted-foreground">CONFIGURED</span>
              </div>
            </div>
          </div>
        </div>

        <div className="p-6 border rounded-xl bg-card">
          <div className="flex items-center gap-3 mb-4">
            <Database className="w-6 h-6 text-primary" />
            <h2 className="text-xl font-semibold">Fabric Statistics</h2>
          </div>
          <div className="space-y-2 text-sm">
            <p className="text-muted-foreground italic">
              Phase 2.6 targets achieved. Monitoring real-time futures ticks (MES, MNQ) and Options Greeks.
            </p>
            <div className="mt-4 flex gap-2">
              <Badge variant="neutral">ticks_buffer: 512</Badge>
              <Badge variant="neutral">greeks_cache: 10s</Badge>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
