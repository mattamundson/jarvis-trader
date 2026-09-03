"use client";

import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { localFetcher, relativeTime, UnreachableNote } from "./shared";
import type { RuntimeSnapshotSummary } from "@/lib/runtimeSnapshot";

function statusBadge(data: RuntimeSnapshotSummary | undefined): {
  label: string;
  variant: "bull" | "bear" | "warn" | "info" | "neutral";
} {
  if (!data) return { label: "LOADING", variant: "neutral" };
  if (!data.available) return { label: "MISSING", variant: "warn" };
  if (data.freshness === "stale") return { label: "STALE", variant: "warn" };
  if (data.engine.live_trading === true || data.ports.ib_live_4001_open === true) {
    return { label: "RISK", variant: "bear" };
  }
  if (data.engine.reachable === false || data.ports.engine_8010_open === false) {
    return { label: "ENGINE DOWN", variant: "bear" };
  }
  return { label: "FRESH", variant: "bull" };
}

function Pill({
  label,
  value,
  variant,
}: {
  label: string;
  value: string;
  variant: "bull" | "bear" | "warn" | "info" | "neutral";
}) {
  return (
    <div className="flex items-center gap-1.5 rounded-lg border border-border bg-muted/30 px-2.5 py-1.5">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <Badge variant={variant}>{value}</Badge>
    </div>
  );
}

export function RuntimeSnapshotPanel() {
  const { data, error, isLoading } = useSWR<RuntimeSnapshotSummary>(
    "/api/runtime-snapshot",
    localFetcher,
    { refreshInterval: 30_000 }
  );

  const badge = statusBadge(data);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <CardTitle>Runtime Snapshot</CardTitle>
            <p className="text-xs text-muted-foreground mt-1">
              Read-only A-01 operator artifact — works even when the engine is down
            </p>
          </div>
          <Badge variant={badge.variant}>{isLoading ? "LOADING" : badge.label}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {error ? (
          <UnreachableNote endpoint="/api/runtime-snapshot" />
        ) : data ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Pill
                label="Captured"
                value={data.generated_at ? relativeTime(data.generated_at) : "—"}
                variant={data.freshness === "stale" ? "warn" : data.freshness === "fresh" ? "bull" : "neutral"}
              />
              <Pill
                label="Branch"
                value={data.repository.branch ?? "—"}
                variant="info"
              />
              <Pill
                label="Dirty"
                value={data.repository.dirty_count == null ? "—" : String(data.repository.dirty_count)}
                variant={data.repository.dirty_count && data.repository.dirty_count > 0 ? "warn" : "bull"}
              />
              <Pill label="HEAD" value={data.repository.head_short ?? "—"} variant="neutral" />
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 border-t border-border pt-3">
              <div className="space-y-2">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Ports</p>
                <div className="flex flex-wrap gap-2">
                  <Pill
                    label=":8010"
                    value={data.ports.engine_8010_open ? "OPEN" : "CLOSED"}
                    variant={data.ports.engine_8010_open ? "bull" : "bear"}
                  />
                  <Pill
                    label=":3010"
                    value={data.ports.dashboard_3010_open ? "OPEN" : "CLOSED"}
                    variant={data.ports.dashboard_3010_open ? "bull" : "warn"}
                  />
                  <Pill
                    label=":4002"
                    value={data.ports.ib_paper_4002_open ? "OPEN" : "CLOSED"}
                    variant={data.ports.ib_paper_4002_open ? "bull" : "warn"}
                  />
                  <Pill
                    label=":4001"
                    value={data.ports.ib_live_4001_open ? "OPEN" : "CLOSED"}
                    variant={data.ports.ib_live_4001_open ? "bear" : "bull"}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Runtime truth</p>
                <div className="flex flex-wrap gap-2">
                  <Pill
                    label="Engine"
                    value={data.engine.reachable ? (data.engine.status ?? "OK").toUpperCase() : "UNREACHABLE"}
                    variant={data.engine.reachable ? "bull" : "bear"}
                  />
                  <Pill
                    label="Trading"
                    value={data.engine.live_trading ? "LIVE" : data.engine.paper_trading ? "PAPER" : "—"}
                    variant={data.engine.live_trading ? "bear" : data.engine.paper_trading ? "info" : "neutral"}
                  />
                  <Pill
                    label="Kill switch"
                    value={data.engine.kill_switch_active ? "ACTIVE" : "OFF"}
                    variant={data.engine.kill_switch_active ? "bear" : "bull"}
                  />
                  <Pill
                    label="IBKR"
                    value={data.engine.ibkr_connected ? "CONNECTED" : "DISCONNECTED"}
                    variant={data.engine.ibkr_connected ? "bull" : "warn"}
                  />
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 border-t border-border pt-3">
              <div className="space-y-2">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Eligibility snapshot</p>
                <div className="flex flex-wrap gap-2">
                  <Pill label="Total" value={data.eligibility.total == null ? "—" : String(data.eligibility.total)} variant="neutral" />
                  <Pill label="Tradeable" value={data.eligibility.tradeable == null ? "—" : String(data.eligibility.tradeable)} variant="bull" />
                  <Pill label="Enabled" value={data.eligibility.enabled == null ? "—" : String(data.eligibility.enabled)} variant="info" />
                  <Pill
                    label="Disagreements"
                    value={data.eligibility.disagreements == null ? "—" : String(data.eligibility.disagreements)}
                    variant={(data.eligibility.disagreements ?? 0) > 0 ? "bear" : "bull"}
                  />
                </div>
                {data.eligibility.enabled_not_tradeable.length > 0 && (
                  <p className="text-[11px] text-warn">
                    Enabled but not tradeable: <span className="font-mono">{data.eligibility.enabled_not_tradeable.join(", ")}</span>
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Backup health</p>
                <div className="flex flex-wrap gap-2">
                  <Pill
                    label="Backup"
                    value={data.backup.healthy === null ? "—" : data.backup.healthy ? "HEALTHY" : "UNHEALTHY"}
                    variant={data.backup.healthy === null ? "neutral" : data.backup.healthy ? "bull" : "bear"}
                  />
                  <Pill
                    label="Count"
                    value={data.backup.backup_count == null ? "—" : String(data.backup.backup_count)}
                    variant="neutral"
                  />
                  <Pill
                    label="Age"
                    value={data.backup.last_backup_age_hours == null ? "—" : `${data.backup.last_backup_age_hours.toFixed(1)}h`}
                    variant={data.backup.last_backup_age_hours != null && data.backup.last_backup_age_hours > 24 ? "warn" : "bull"}
                  />
                </div>
              </div>
            </div>

            <div className="border-t border-border pt-3 space-y-2">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Findings</p>
              {data.findings.length === 0 ? (
                <p className="text-xs text-muted-foreground">No snapshot findings.</p>
              ) : (
                <ul className="space-y-1">
                  {data.findings.map((finding) => (
                    <li key={finding} className="text-[11px] text-muted-foreground font-mono break-words">
                      • {finding}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
