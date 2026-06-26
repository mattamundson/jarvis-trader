"use client";
import Link from "next/link";
import useSWR from "swr";
import { fetchMasterStatus, aggregationBannerState } from "@/lib/masterApi";
import { DomainTile } from "@/components/master/DomainTile";
import { CommandChat } from "@/components/master/CommandChat";
import { SchedulerPanel } from "@/components/master/SchedulerPanel";

const ORDER = ["personal", "trading", "finances", "career", "health", "knowledge", "system"];

export default function MasterPage() {
  const { data, error } = useSWR("master-status", fetchMasterStatus, {
    refreshInterval: 15000,
  });

  if (error) return (
    <main className="p-6 space-y-3">
      <h1 className="text-2xl font-bold text-zinc-100">Master Jarvis</h1>
      <div className="rounded-xl border border-red-800/40 bg-red-950/20 p-4">
        <p className="font-mono text-sm text-red-400">Master API unreachable — is the master-api service running on :8030?</p>
        <p className="font-mono text-xs text-zinc-500 mt-1">Expected: http://127.0.0.1:8030/master/status</p>
      </div>
    </main>
  );
  if (!data) return (
    <main className="p-6 space-y-4">
      <h1 className="text-2xl font-bold text-zinc-100">Master Jarvis</h1>
      <p className="text-xs text-zinc-500">Loading mission control…</p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[1,2,3,4,5,6].map((i) => (
          <div key={i} className="h-32 animate-pulse rounded-xl border border-zinc-800 bg-zinc-900/60" />
        ))}
      </div>
    </main>
  );

  const tiles = ORDER.filter((d) => data.domains[d]).map((d) => data.domains[d]);
  // Split-brain circuit-breaker: master-api answered (200) but may be serving a
  // cache that stopped refreshing. Surface that explicitly so the tiles below are
  // not mistaken for live numbers.
  const banner = aggregationBannerState(data, false);

  return (
    <main className="p-6">
      <h1 className="mb-1 text-2xl font-bold text-zinc-100">Master Jarvis</h1>
      <p className="mb-6 text-sm text-zinc-400">
        Mission control · updated {new Date(data.ts).toLocaleTimeString()}
      </p>
      {banner.degraded && (
        <div className="mb-6 rounded-xl border border-amber-700/50 bg-amber-950/30 p-4">
          <p className="font-mono text-sm text-amber-400">⚠ {banner.reason}</p>
          <p className="font-mono text-xs text-zinc-500 mt-1">
            Tiles below may be stale — master-api is not refreshing these domains.
          </p>
        </div>
      )}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {tiles.map((s) => {
          const href =
            s.domain === "finances"
              ? "/master/finances"
              : s.domain === "trading"
                ? "/master/trading"
                : null;
          return href ? (
            <Link key={s.domain} href={href} className="block">
              <DomainTile s={s} interactive />
            </Link>
          ) : (
            <DomainTile key={s.domain} s={s} />
          );
        })}
      </div>
      <SchedulerPanel />
      <CommandChat />
    </main>
  );
}
