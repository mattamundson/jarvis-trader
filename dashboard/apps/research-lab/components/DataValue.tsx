"use client";

// <DataValue> — the shared provenance-aware primitive (Phase 1 P1.2).
//
// Renders a value together with a source/staleness badge derived from its
// DataEnvelope, so a number can never be shown without its provenance. Reuses
// the canonical `live`/`static` badge variants and the Trust Pane dot pattern
// (pulsing dot = LIVE, muted = STATIC/STALE). The LIVE badge is gated on the
// server's derived `is_live`; a value that ages past its freshness window
// downgrades to STALE on screen via `useProvenance`. No bare fetch, no new
// badge variants.

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { type DataEnvelope, type ProvenanceView } from "@/lib/provenance";
import { useProvenance } from "@/lib/useProvenance";

function fmtAge(seconds: number | null): string {
  if (seconds == null) return "";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m ago`;
}

/**
 * The provenance badge on its own — reusable when a panel already renders the
 * value itself and only needs the honest live/static/stale marker.
 */
export function ProvenanceBadge({
  view,
  className,
}: {
  view: ProvenanceView;
  className?: string;
}) {
  const title = [
    `source: ${view.source}`,
    view.ageSeconds != null ? fmtAge(view.ageSeconds) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Badge variant={view.badgeVariant} className={className} title={title}>
      <span className="flex items-center gap-1">
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            view.status === "live"
              ? "bg-bull animate-pulse"
              : "bg-muted-foreground",
          )}
        />
        {view.label}
      </span>
    </Badge>
  );
}

interface DataValueProps<T> {
  envelope: DataEnvelope<T> | null | undefined;
  /** Formatter for the underlying value. Defaults to String(value). */
  format?: (value: T) => string;
  /** Rendered when the value is null/unavailable. Default "—". */
  placeholder?: string;
  /** Show the provenance badge. Default true. */
  showBadge?: boolean;
  className?: string;
  valueClassName?: string;
}

export function DataValue<T>({
  envelope,
  format,
  placeholder = "—",
  showBadge = true,
  className,
  valueClassName,
}: DataValueProps<T>) {
  const view = useProvenance(envelope);
  const raw = envelope?.value;
  const text =
    raw == null ? placeholder : format ? format(raw) : String(raw);

  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <span className={cn("font-mono", valueClassName)}>{text}</span>
      {showBadge && <ProvenanceBadge view={view} />}
    </span>
  );
}
