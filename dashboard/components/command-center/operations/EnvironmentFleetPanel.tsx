"use client";

import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { localFetcher, LoadingRows, relativeTime, UnreachableNote } from "./shared";

// Response shape of the local /api/fleet route (app/api/fleet/route.ts)
interface FleetLoop {
  id: string;
  status: string;
  runner: string;
  schedule: string;
  last_heartbeat: string | null;
  color: "GREEN" | "RED" | "ERROR" | "UNKNOWN";
  stale: boolean;
}

interface FleetResponse {
  canary: {
    overall: "GREEN" | "RED" | "UNKNOWN";
    failing: string[];
    generated_at: string | null;
  };
  counts: { total: number; green: number; red: number; stale: number };
  red_loops: string[];
  stale_loops: string[];
  loops: FleetLoop[];
  errors: { registry: string | null; canary: string | null };
}

function CountPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "bull" | "bear" | "warn";
}) {
  const cls =
    tone === "bull"
      ? "border-bull/25 bg-bull/10 text-bull"
      : tone === "bear"
        ? "border-bear/25 bg-bear/10 text-bear"
        : "border-warn/25 bg-warn/10 text-warn";
  return (
    <div className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 ${cls}`}>
      <span className="font-mono text-sm font-bold">{value}</span>
      <span className="text-[11px] uppercase tracking-wide">{label}</span>
    </div>
  );
}

export function EnvironmentFleetPanel() {
  const { data, error, isLoading } = useSWR<FleetResponse>("/api/fleet", localFetcher, {
    refreshInterval: 15_000,
  });

  const loops = Array.isArray(data?.loops) ? data.loops : [];
  const canary = data?.canary ?? { overall: "UNKNOWN" as const, failing: [], generated_at: null };
  const failing = Array.isArray(canary.failing) ? canary.failing : [];
  const counts = data?.counts ?? { total: loops.length, green: 0, red: 0, stale: 0 };
  const errors = data?.errors ?? { registry: null, canary: null };
  const redLoops = Array.isArray(data?.red_loops) ? data.red_loops : [];
  const staleLoops = Array.isArray(data?.stale_loops) ? data.stale_loops : [];
  const hb = (id: string) => loops.find((l) => l.id === id)?.last_heartbeat;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Environment Fleet</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {error ? (
          <UnreachableNote endpoint="/api/fleet" />
        ) : isLoading ? (
          <LoadingRows rows={3} />
        ) : data ? (
          <>
            {/* Canary verdict */}
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
                env-canary
              </span>
              <Badge
                variant={
                  canary.overall === "GREEN"
                    ? "bull"
                    : canary.overall === "RED"
                      ? "bear"
                      : "neutral"
                }
              >
                {canary.overall}
              </Badge>
              {canary.generated_at && (
                <span className="font-mono text-[10px] text-muted-foreground">
                  {relativeTime(canary.generated_at)}
                </span>
              )}
              {errors.canary && (
                <span className="text-[10px] text-warn">canary report unreadable</span>
              )}
            </div>

            {failing.length > 0 && (
              <ul className="space-y-1">
                {failing.map((f) => (
                  <li key={f} className="flex items-start gap-1.5 text-[11px]">
                    <Badge variant="bear" className="shrink-0">
                      FAIL
                    </Badge>
                    <span className="font-mono text-muted-foreground break-all">{f}</span>
                  </li>
                ))}
              </ul>
            )}

            {/* Loop counts */}
            <div className="flex flex-wrap gap-2 border-t border-border pt-3">
              <CountPill label="green" value={counts.green} tone="bull" />
              <CountPill label="red" value={counts.red} tone="bear" />
              <CountPill label="stale" value={counts.stale} tone="warn" />
              <div className="flex items-center gap-1.5 rounded-lg border border-border bg-muted/30 px-3 py-1.5">
                <span className="font-mono text-sm font-bold text-foreground">
                  {counts.total}
                </span>
                <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
                  loops
                </span>
              </div>
            </div>

            {/* Red / stale loop names */}
            {(redLoops.length > 0 || staleLoops.length > 0) && (
              <div className="space-y-1.5">
                {redLoops.map((id) => (
                  <div key={`red-${id}`} className="flex items-center gap-2 text-[11px]">
                    <Badge variant="bear" className="shrink-0">
                      RED
                    </Badge>
                    <span className="font-mono text-foreground">{id}</span>
                    <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                      {relativeTime(hb(id)?.split(/\s+/)[0])}
                    </span>
                  </div>
                ))}
                {staleLoops
                  .filter((id) => !redLoops.includes(id))
                  .map((id) => (
                    <div key={`stale-${id}`} className="flex items-center gap-2 text-[11px]">
                      <Badge variant="warn" className="shrink-0">
                        STALE
                      </Badge>
                      <span className="font-mono text-foreground">{id}</span>
                      <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                        {relativeTime(hb(id)?.split(/\s+/)[0])}
                      </span>
                    </div>
                  ))}
              </div>
            )}
            {errors.registry && (
              <p className="text-[11px] text-warn">Registry unreadable: {errors.registry}</p>
            )}
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
