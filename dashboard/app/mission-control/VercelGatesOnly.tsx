"use client";

import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { HermesGatesReport } from "@/lib/hermesGates";
import { fetcher, localFetcher, UnreachableNote } from "./components/shared";

/** Hosted audience: no positions, quantities, P&L, or order-entry panels. */
export function VercelGatesOnly() {
  const { data: gates, error: gatesError } = useSWR<HermesGatesReport>(
    "/api/operator/gates", localFetcher, { refreshInterval: 15_000 },
  );
  const { data: lockout, error: lockoutError } = useSWR<{
    is_halted?: boolean;
    halt_until?: string | null;
  }>("/safety/loss-tracker/status", fetcher, { refreshInterval: 15_000 });

  return (
    <main className="mx-auto max-w-3xl space-y-6 px-6 py-6">
      <h1 className="text-xl font-bold">MISSION CONTROL — read-only</h1>
      <Card>
        <CardHeader><CardTitle>Hermes gates</CardTitle></CardHeader>
        <CardContent>
          {gatesError ? <UnreachableNote endpoint="/api/operator/gates" /> : (
            <p className="text-sm text-muted-foreground">
              {gates?.message ?? "Loading gates…"}
            </p>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Lockout</CardTitle></CardHeader>
        <CardContent>
          {lockoutError ? <UnreachableNote endpoint="/safety/loss-tracker/status" /> : (
            <p className="text-sm">
              {lockout?.is_halted == null ? "Lockout status unavailable" :
                lockout.is_halted ? "Halted" : "Not halted"}
              {lockout?.halt_until ? ` — until ${lockout.halt_until}` : ""}
            </p>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
