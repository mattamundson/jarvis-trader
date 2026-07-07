"use client";

import { AlertTriangle } from "lucide-react";
import { fetchEngine } from "@/lib/api";

/**
 * Shared SWR fetcher for Mission Control engine panels — routes through the
 * existing fetchEngine() proxy (never a direct engine URL / hardcoded key).
 */
export function fetcher<T>(path: string): Promise<T> {
  return fetchEngine<T>(path);
}

/**
 * Fetcher for the dashboard's OWN same-origin API routes (e.g. /api/fleet).
 * These are Next.js route handlers reading local disk state, not engine
 * endpoints, so they bypass the /api/engine proxy entirely.
 */
export async function localFetcher<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} error ${res.status}`);
  return res.json() as Promise<T>;
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diffSec = Math.floor((Date.now() - then) / 1000);
  if (diffSec < 0) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

export function formatUsd(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n >= 0 ? "+" : "-";
  return `${sign}$${Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

export function formatPct(fraction: number | null | undefined, digits = 2): string {
  if (fraction == null || Number.isNaN(fraction)) return "—";
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function UnreachableNote({ endpoint }: { endpoint: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-bear/20 bg-bear/5 px-3 py-2">
      <AlertTriangle className="h-3.5 w-3.5 text-bear shrink-0" />
      <span className="text-xs font-semibold text-bear">UNREACHABLE</span>
      <span className="ml-auto font-mono text-[10px] text-muted-foreground">{endpoint}</span>
    </div>
  );
}

export function LoadingRows({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2 animate-pulse">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-4 rounded bg-muted" />
      ))}
    </div>
  );
}
