"use client";
import Link from "next/link";
import useSWR from "swr";
import { fetchMasterStatus } from "@/lib/masterApi";
import { DomainTile } from "@/components/master/DomainTile";
import { CommandChat } from "@/components/master/CommandChat";

const ORDER = ["personal", "trading", "finances", "career", "health", "knowledge", "system"];

export default function MasterPage() {
  const { data, error } = useSWR("master-status", fetchMasterStatus, {
    refreshInterval: 15000,
  });

  if (error) return <div className="p-6 text-red-400">Master API unreachable.</div>;
  if (!data) return <div className="p-6 text-zinc-400">Loading mission control…</div>;

  const tiles = ORDER.filter((d) => data.domains[d]).map((d) => data.domains[d]);

  return (
    <main className="p-6">
      <h1 className="mb-1 text-2xl font-bold text-zinc-100">Master Jarvis</h1>
      <p className="mb-6 text-sm text-zinc-400">
        Mission control · updated {new Date(data.ts).toLocaleTimeString()}
      </p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {tiles.map((s) =>
          s.domain === "finances" || s.domain === "trading" ? (
            <Link
              key={s.domain}
              href={s.domain === "finances" ? "/master/finances" : "/master/trading"}
              className="block"
            >
              <DomainTile s={s} />
            </Link>
          ) : (
            <DomainTile key={s.domain} s={s} />
          ),
        )}
      </div>
      <CommandChat />
    </main>
  );
}
