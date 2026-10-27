"use client";

import useSWR from "swr";
import { Radar } from "lucide-react";
import { fetcher, localFetcher } from "./components/shared";
import { GatesBlock, LockoutBlock } from "./components/OperatorScoreboard";
import type { HermesGatesReport } from "@/lib/hermesGates";

interface LossTrackerStatus {
  is_halted?: boolean;
  halt_until?: string | null;
}

/**
 * Public Vercel audience. Gates and lockout only.
 * This module does not import position, P&L, or account panels.
 */
export function VercelGatesOnly() {
  const { data: lockout, error: lockoutError } = useSWR<LossTrackerStatus>(
    "/safety/loss-tracker/status",
    fetcher,
    { refreshInterval: 15_000 },
  );
  const { data: gates, error: gatesError } = useSWR<HermesGatesReport>(
    "/api/operator/gates",
    localFetcher,
    { refreshInterval: 15_000 },
  );

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] items-center gap-3 px-6 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
            <Radar className="h-5 w-5 text-accent" />
          </div>
          <div>
            <h1 className="font-bold tracking-tight text-foreground">MISSION CONTROL</h1>
            <p className="text-xs text-muted-foreground">Gates and lockout only</p>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1600px] space-y-6 px-6 py-6">
        <section className="rounded-xl border border-border bg-card p-4">
          <LockoutBlock lockout={lockout} error={lockoutError} />
          <div className="mt-4">
            <GatesBlock gates={gates} error={gatesError} />
          </div>
        </section>
      </main>
    </div>
  );
}
