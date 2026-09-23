"use client";

import useSWR from "swr";
import { Flag } from "lucide-react";
import { fetchFeatureFlags, type FeatureFlagInfo } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { POLL_INTERVAL } from "@/lib/polling-config";

// ── Feature flags registry (GET /flags/) — READ-ONLY (Plan Phase 8 row 6) ────
// A richer, dedicated view of the same registry the "Feature Flags" category
// on this page already surfaces via /config/overview (boolean-only, no
// description/category/requires_restart/source). This panel adds that
// metadata but is intentionally display-only: PUT /flags/{name} and
// DELETE /flags/{name} both exist on the engine (see components/
// FeatureFlagsPanel.tsx, an orphaned toggle-capable component already in this
// tree that is NOT mounted anywhere and must stay that way this wave) but
// plan decision D9 says no toggle UI ships this wave -- a toggle would lie
// for any flag with requires_restart=true, since the write persists
// immediately but the behavior stays inert until the engine process restarts.

function formatFlagName(name: string): string {
  return name.replace(/[_-]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function FlagRow({ flag }: { flag: FeatureFlagInfo }) {
  return (
    <div
      className={`flex items-start justify-between gap-4 rounded-lg border px-3 py-2 ${
        flag.enabled ? "border-border bg-card/60" : "border-border/50 bg-muted/20"
      }`}
    >
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-semibold text-foreground">{formatFlagName(flag.name)}</span>
          <Badge variant="neutral" className="text-[10px] px-1.5 py-0 font-mono">
            {flag.category}
          </Badge>
          {flag.source === "runtime" && (
            <Badge variant="info" className="text-[10px] px-1.5 py-0">
              runtime override
            </Badge>
          )}
          {flag.requires_restart && (
            <Badge variant="warn" className="text-[10px] px-1.5 py-0">
              requires restart
            </Badge>
          )}
        </div>
        {flag.description && (
          <p className="text-[11px] text-muted-foreground leading-relaxed">{flag.description}</p>
        )}
      </div>
      <Badge variant={flag.enabled ? "bull" : "neutral"} className="shrink-0">
        {flag.enabled ? "on" : "off"}
      </Badge>
    </div>
  );
}

/**
 * Read-only feature-flags registry panel. Mounted on /config. Never issues a
 * PUT/DELETE against /flags/{name} -- GET /flags/ only. See D9 in Plan Phase 8
 * row 6: a toggle here would lie about taking effect immediately.
 */
export function FeatureFlagsReadOnlyPanel() {
  const { data, error, isLoading } = useSWR<FeatureFlagInfo[]>(
    "feature-flags-readonly",
    fetchFeatureFlags,
    { refreshInterval: POLL_INTERVAL.SLOW, shouldRetryOnError: false }
  );

  const flags = data ?? [];
  const enabledCount = flags.filter((f) => f.enabled).length;

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Flag className="h-4 w-4 text-accent" />
          <span className="text-sm font-semibold text-zinc-200">Feature Flags Registry</span>
        </div>
        {data && (
          <span className="text-[11px] text-zinc-500 font-mono">
            {enabledCount}/{flags.length} enabled
          </span>
        )}
      </div>

      <p className="text-[11px] text-zinc-500">
        Read-only. Full two-layer registry (config default + runtime override) — toggling
        requires an engine restart to take effect for any flag marked &quot;requires restart&quot;,
        so no toggle control is exposed here.
      </p>

      {isLoading && !data && (
        <p className="text-xs text-zinc-500 animate-pulse">Loading feature flag registry…</p>
      )}
      {error && (
        <p className="text-xs text-zinc-500">
          /flags/ unreachable — engine offline or endpoint not deployed.
        </p>
      )}
      {data && flags.length === 0 && (
        <p className="text-xs text-zinc-500">No feature flags registered.</p>
      )}

      {flags.length > 0 && (
        <div className="space-y-1.5">
          {flags.map((flag) => (
            <FlagRow key={flag.name} flag={flag} />
          ))}
        </div>
      )}
    </div>
  );
}
