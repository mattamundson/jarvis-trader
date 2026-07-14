"use client";

// SessionBriefPanel — the flagship "Session Brief" surface (Phase 5 P5.2).
//
// Renders the proactive advisor brief the engine assembles from the pipeline's
// EXISTING reasoning (GET /brief/session). It never fabricates: an action whose
// snapshot carried no reasoning shows an honest gap message, and every action
// carries an honest staleness marker built with the canonical live/static
// provenance badges (Phase 1 pattern). No bare fetch — data comes through
// fetchSessionBrief / fetchEngine in lib/api.ts.

import useSWR from "swr";
import { Lightbulb, AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { fetchSessionBrief } from "@/lib/api";
import type {
  SessionBriefResponse,
  SessionBriefAction,
} from "@/lib/api";

const REFRESH_MS = 30_000;

function fmtAge(seconds: number | null): string {
  if (seconds == null) return "age unknown";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m ago`;
}

function actionVariant(action: string): "bull" | "bear" | "neutral" {
  const a = action.toLowerCase();
  if (a === "buy" || a === "long") return "bull";
  if (a === "sell" || a === "short") return "bear";
  return "neutral";
}

/**
 * Honest freshness badge for one action. Reuses the canonical `live`/`static`
 * variants: a fresh, reasoning-backed, non-degraded action reads LIVE; anything
 * stale / unknown-age / reasoning-less / degraded reads STALE — never promoted.
 */
function StalenessBadge({ action }: { action: SessionBriefAction }) {
  const { staleness, data_degraded } = action;
  const live = !data_degraded && !staleness.is_stale && !staleness.unknown_age;
  const label = staleness.unknown_age
    ? "AGE UNKNOWN"
    : staleness.is_stale
      ? "STALE"
      : live
        ? "LIVE"
        : "DEGRADED";
  const title = [
    staleness.as_of ? `as of ${staleness.as_of}` : null,
    fmtAge(staleness.age_seconds),
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Badge variant={live ? "live" : "static"} title={title}>
      <span className="flex items-center gap-1">
        <span
          className={`h-1.5 w-1.5 rounded-full ${
            live ? "bg-bull animate-pulse" : "bg-muted-foreground"
          }`}
        />
        {label}
      </span>
    </Badge>
  );
}

function ActionCard({ action }: { action: SessionBriefAction }) {
  const conf =
    action.confidence != null
      ? `${Math.round(action.confidence * 100)}%`
      : "—";
  return (
    <div className="rounded-lg border border-border bg-background/50 p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-mono font-bold text-sm text-foreground">
            {action.symbol}
          </span>
          <Badge variant={actionVariant(action.action)}>
            {action.action.toUpperCase()}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-muted-foreground tabular-nums">
            conf {conf}
          </span>
          <StalenessBadge action={action} />
        </div>
      </div>
      <p
        className={`text-xs leading-relaxed ${
          action.reasoning_available
            ? "text-foreground/80"
            : "text-muted-foreground italic"
        }`}
      >
        {action.why}
      </p>
      {action.reasoning_available && action.reasoning_sources.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          {action.reasoning_sources.map((src) => (
            <Badge key={src} variant="neutral" className="text-[10px]">
              {src}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

export function SessionBriefPanel() {
  const { data, error } = useSWR<SessionBriefResponse>(
    "session-brief",
    () => fetchSessionBrief(10, 3),
    { refreshInterval: REFRESH_MS, shouldRetryOnError: false }
  );

  const actions = data?.actions ?? [];
  const degraded = error != null || data?.degraded !== false;

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Lightbulb className="h-4 w-4 text-accent" />
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Session Brief
          </span>
          <span className="text-[10px] text-muted-foreground/70">
            advisor recommendations
          </span>
        </div>
        {degraded && (
          <Badge variant="static">
            <span className="flex items-center gap-1">
              <AlertTriangle className="h-3 w-3" />
              DEGRADED
            </span>
          </Badge>
        )}
      </div>

      {error ? (
        <p className="text-xs text-muted-foreground">
          Brief unavailable — engine not reachable.
        </p>
      ) : actions.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          {data?.note ??
            "No recent pipeline decisions to advise on yet."}
        </p>
      ) : (
        <div className="space-y-2">
          {actions.map((action, i) => (
            <ActionCard key={`${action.symbol}-${i}`} action={action} />
          ))}
        </div>
      )}
    </div>
  );
}

export default SessionBriefPanel;
