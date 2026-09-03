"use client";

import { AlertTriangle, Clock3 } from "lucide-react";
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

function integrityVariant(status: "pass" | "fail" | "unknown" | undefined): "bull" | "bear" | "warn" | "neutral" {
  if (status === "pass") return "bull";
  if (status === "fail") return "bear";
  return "neutral";
}

function formatAgeSeconds(ageSeconds: number | null | undefined): string {
  if (ageSeconds == null || Number.isNaN(ageSeconds)) return "—";
  if (ageSeconds < 60) return `${ageSeconds}s`;
  const ageMinutes = Math.floor(ageSeconds / 60);
  if (ageMinutes < 60) return `${ageMinutes}m`;
  const ageHours = ageSeconds / 3600;
  if (ageHours < 24) return `${ageHours.toFixed(ageHours >= 10 ? 0 : 1)}h`;
  const ageDays = ageHours / 24;
  return `${ageDays.toFixed(ageDays >= 10 ? 0 : 1)}d`;
}

function freshnessState(data: RuntimeSnapshotSummary | undefined): {
  level: "fresh" | "aging" | "stale" | "unknown";
  label: string;
  detail: string;
  variant: "bull" | "warn" | "neutral";
} {
  if (!data || data.age_seconds == null || data.freshness === "unknown") {
    return {
      level: "unknown",
      label: "SNAPSHOT AGE UNKNOWN",
      detail: "The operator artifact does not include a trustworthy capture timestamp.",
      variant: "neutral",
    };
  }

  if (data.freshness === "stale") {
    return {
      level: "stale",
      label: `STALE SNAPSHOT — ${formatAgeSeconds(data.age_seconds)} old`,
      detail: "Refresh the runtime truth artifact before trusting Mission Control state.",
      variant: "warn",
    };
  }

  if (data.age_seconds >= 6 * 60 * 60) {
    return {
      level: "aging",
      label: `AGING SNAPSHOT — ${formatAgeSeconds(data.age_seconds)} old`,
      detail: "Still inside the 24h freshness window, but operator truth is aging.",
      variant: "warn",
    };
  }

  return {
    level: "fresh",
    label: `FRESH SNAPSHOT — ${formatAgeSeconds(data.age_seconds)} old`,
    detail: "Runtime truth was captured recently enough to trust this panel at a glance.",
    variant: "bull",
  };
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
  const freshness = freshnessState(data);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <CardTitle>Runtime Snapshot</CardTitle>
            <p className="text-xs text-muted-foreground mt-1">
              Read-only A-01 operator artifact + checkout integrity evidence
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
            <div
              className={
                freshness.level === "fresh"
                  ? "flex items-start gap-2 rounded-lg border border-bull/25 bg-bull/5 px-3 py-2"
                  : freshness.level === "unknown"
                    ? "flex items-start gap-2 rounded-lg border border-border bg-muted/20 px-3 py-2"
                    : "flex items-start gap-2 rounded-lg border border-warn/30 bg-warn/10 px-3 py-2"
              }
            >
              {freshness.level === "fresh" ? (
                <Clock3 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-bull" />
              ) : freshness.level === "unknown" ? (
                <Clock3 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              ) : (
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warn" />
              )}
              <div className="space-y-0.5">
                <p className="text-[11px] font-semibold tracking-wide text-foreground">{freshness.label}</p>
                <p className="text-[11px] text-muted-foreground">{freshness.detail}</p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Pill
                label="Captured"
                value={data.generated_at ? relativeTime(data.generated_at) : "—"}
                variant={data.freshness === "stale" ? "warn" : data.freshness === "fresh" ? "bull" : "neutral"}
              />
              <Pill label="Age" value={formatAgeSeconds(data.age_seconds)} variant={freshness.variant} />
              <Pill label="SLA" value="24h" variant="neutral" />
              <Pill label="Branch" value={data.repository.branch ?? "—"} variant="info" />
              <Pill
                label="Dirty"
                value={data.repository.dirty_count == null ? "—" : String(data.repository.dirty_count)}
                variant={data.repository.dirty_count && data.repository.dirty_count > 0 ? "warn" : "bull"}
              />
              <Pill label="HEAD" value={data.repository.head_short ?? "—"} variant="neutral" />
              <Pill
                label="Contract"
                value={data.contract.required_sections_present ? "COMPLETE" : "INCOMPLETE"}
                variant={data.contract.required_sections_present ? "bull" : "bear"}
              />
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 border-t border-border pt-3">
              <div className="space-y-2">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Ports</p>
                <div className="flex flex-wrap gap-2">
                  <Pill label=":8010" value={data.ports.engine_8010_open ? "OPEN" : "CLOSED"} variant={data.ports.engine_8010_open ? "bull" : "bear"} />
                  <Pill label=":3010" value={data.ports.dashboard_3010_open ? "OPEN" : "CLOSED"} variant={data.ports.dashboard_3010_open ? "bull" : "warn"} />
                  <Pill label=":4002" value={data.ports.ib_paper_4002_open ? "OPEN" : "CLOSED"} variant={data.ports.ib_paper_4002_open ? "bull" : "warn"} />
                  <Pill label=":4001" value={data.ports.ib_live_4001_open ? "OPEN" : "CLOSED"} variant={data.ports.ib_live_4001_open ? "bear" : "bull"} />
                </div>
              </div>

              <div className="space-y-2">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Runtime truth</p>
                <div className="flex flex-wrap gap-2">
                  <Pill label="Engine" value={data.engine.reachable ? (data.engine.status ?? "OK").toUpperCase() : "UNREACHABLE"} variant={data.engine.reachable ? "bull" : "bear"} />
                  <Pill label="Trading" value={data.engine.live_trading ? "LIVE" : data.engine.paper_trading ? "PAPER" : "—"} variant={data.engine.live_trading ? "bear" : data.engine.paper_trading ? "info" : "neutral"} />
                  <Pill label="Kill switch" value={data.engine.kill_switch_active ? "ACTIVE" : "OFF"} variant={data.engine.kill_switch_active ? "bear" : "bull"} />
                  <Pill label="IBKR" value={data.engine.ibkr_connected ? "CONNECTED" : "DISCONNECTED"} variant={data.engine.ibkr_connected ? "bull" : "warn"} />
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
                  <Pill label="Disagreements" value={data.eligibility.disagreements == null ? "—" : String(data.eligibility.disagreements)} variant={(data.eligibility.disagreements ?? 0) > 0 ? "bear" : "bull"} />
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
                  <Pill label="Backup" value={data.backup.healthy === null ? "—" : data.backup.healthy ? "HEALTHY" : "UNHEALTHY"} variant={data.backup.healthy === null ? "neutral" : data.backup.healthy ? "bull" : "bear"} />
                  <Pill label="Count" value={data.backup.backup_count == null ? "—" : String(data.backup.backup_count)} variant="neutral" />
                  <Pill label="Age" value={data.backup.last_backup_age_hours == null ? "—" : `${data.backup.last_backup_age_hours.toFixed(1)}h`} variant={data.backup.last_backup_age_hours != null && data.backup.last_backup_age_hours > 24 ? "warn" : "bull"} />
                  <Pill label="Schema" value={data.contract.schema_version == null ? "—" : String(data.contract.schema_version)} variant="neutral" />
                </div>
                {data.contract.missing_sections.length > 0 && (
                  <p className="text-[11px] text-bear">
                    Contract missing: <span className="font-mono">{data.contract.missing_sections.join(", ")}</span>
                  </p>
                )}
              </div>
            </div>

            <div className="border-t border-border pt-3 space-y-2">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Source integrity</p>
              {data.source_integrity?.checks?.length ? (
                <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                  {data.source_integrity.checks.map((check) => (
                    <div key={`${check.label}-${check.repo_root}`} className="rounded-lg border border-border bg-muted/20 p-3 space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <div>
                          <p className="text-xs font-semibold text-foreground">{check.label}</p>
                          <p className="text-[10px] text-muted-foreground font-mono break-all">{check.repo_root}</p>
                        </div>
                        <Badge variant={integrityVariant(check.status)}>{check.status.toUpperCase()}</Badge>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Pill label="Findings" value={String(check.finding_count)} variant={check.finding_count > 0 ? "bear" : "bull"} />
                        <Pill label="Paths" value={String(check.required_path_failures)} variant={check.required_path_failures > 0 ? "bear" : "bull"} />
                        <Pill label="Git" value={String(check.git_metadata_failures)} variant={check.git_metadata_failures > 0 ? "bear" : "bull"} />
                        <Pill label="Actions" value={String(check.workflow_action_failures)} variant={check.workflow_action_failures > 0 ? "bear" : "bull"} />
                      </div>
                      {check.findings.length > 0 && (
                        <ul className="space-y-1">
                          {check.findings.slice(0, 3).map((finding) => (
                            <li key={finding} className="text-[11px] text-muted-foreground font-mono break-words">
                              • {finding}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">No checkout-integrity evidence returned.</p>
              )}
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
