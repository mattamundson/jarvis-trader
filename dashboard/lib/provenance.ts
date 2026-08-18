// Data-provenance envelope — client mirror of engine/data/provenance.py (Phase 1).
//
// A `DataEnvelope` carries a value together with WHERE it came from and HOW FRESH
// it is, so the dashboard can never render a number without its source/staleness.
// `is_live` is DERIVED server-side (tier + freshness + IBKR data-leg connection),
// never hardcoded true. This module classifies an envelope into a display state
// and — critically — can FURTHER downgrade a value that has aged past its
// freshness window since it was fetched (a value that was live at fetch time but
// is now stale must not keep flashing LIVE). LIVE is gated on `is_live`; nothing
// here can promote a value to live.

// Real-time / streaming tiers. Mirrors LIVE_SOURCES in engine/data/provenance.py.
// A value from any of these CAN be live (subject to the server's freshness gate).
//
// "ledger" (P4-2) is distinct from the market-data streaming tiers above: it
// marks a value read synchronously from the closed-trade database, not a price
// feed. It is never cached/delayed the way STATIC_SOURCES are, so it belongs
// here rather than there — a booked trade fact is always current as of the
// request, and should read LIVE, not STATIC, matching the server's honest
// is_live=true verdict (see engine/routers/portfolio_router.py's
// _ledger_envelope).
export const LIVE_SOURCES: ReadonlySet<string> = new Set([
  "ibkr",
  "schwab",
  "tradingview",
  "polygon_stream",
  "redis_fabric",
  "ledger",
]);

export type ProvenanceStatus = "live" | "stale" | "static" | "unavailable";

// The canonical envelope shape emitted by the engine. `as_of` is epoch SECONDS
// (Python time.time()), matching the server dataclass.
export interface DataEnvelope<T = number> {
  value: T | null;
  source: string;
  as_of: number | null;
  is_live: boolean;
  stale_after_s: number;
}

export interface ProvenanceView {
  status: ProvenanceStatus;
  // Canonical badge variant only — never introduces a new variant.
  badgeVariant: "live" | "static";
  label: string; // "LIVE" | "STALE" | "STATIC" | "NO DATA"
  isLive: boolean; // true ONLY when status === "live"
  ageSeconds: number | null; // seconds since as_of, when both as_of and now are known
  source: string;
  asOf: number | null;
}

function isLiveTier(source: string | null | undefined): boolean {
  return !!source && LIVE_SOURCES.has(source.toLowerCase());
}

/**
 * Classify an envelope into a display state. Pure and deterministic — pass
 * `nowMs` to enable client-side age-downgrade; omit it (SSR / first render) to
 * honor the server's verdict without a clock, avoiding hydration mismatch.
 *
 * A LIVE result requires ALL of: a non-null value, a live-tier source, the
 * server's `is_live` true, and (when the clock is known) an age within
 * `stale_after_s`. Anything else is stale (live-tier but downgraded) or static.
 */
export function classifyProvenance<T>(
  env: DataEnvelope<T> | null | undefined,
  nowMs: number | null = null,
): ProvenanceView {
  if (!env || env.value == null) {
    return {
      status: "unavailable",
      badgeVariant: "static",
      label: "NO DATA",
      isLive: false,
      ageSeconds: null,
      source: env?.source ?? "unavailable",
      asOf: env?.as_of ?? null,
    };
  }

  const ageSeconds =
    env.as_of != null && nowMs != null ? nowMs / 1000 - env.as_of : null;
  const agedOut =
    ageSeconds != null && ageSeconds > env.stale_after_s;

  let status: ProvenanceStatus;
  if (!isLiveTier(env.source)) {
    // Cached / delayed / absent tier — never live regardless of age.
    status = "static";
  } else if (env.is_live && !agedOut) {
    status = "live";
  } else {
    // Live-tier value the server downgraded (freshness/connection) or that has
    // since aged past its window — honestly stale, not static.
    status = "stale";
  }

  const label =
    status === "live" ? "LIVE" : status === "stale" ? "STALE" : "STATIC";

  return {
    status,
    badgeVariant: status === "live" ? "live" : "static",
    label,
    isLive: status === "live",
    ageSeconds,
    source: env.source,
    asOf: env.as_of,
  };
}
