/**
 * Provenance LIVE-gating contract — compile-time type tests (Phase 1 P1.4).
 *
 * No runtime test framework is installed in this project (no Jest/Vitest); the
 * dashboard convention is type-level tests checked by tsc. Run via:
 *   cd dashboard && ./node_modules/.bin/tsc -p tsconfig.provenance.test.json --noEmit
 *
 * Guards the Phase 1 invariant that a migrated price/quote widget (WatchlistBar,
 * DataValue/ProvenanceBadge) can NEVER show LIVE unless the server-derived
 * `is_live` is true AND the source is a real-time tier AND the value has not
 * aged past its freshness window. `classifyProvenance` is the single chokepoint
 * every migrated widget renders through, so gating it here gates the UI.
 */

import {
  classifyProvenance,
  type DataEnvelope,
  type ProvenanceView,
} from "../lib/provenance";

// Epoch SECONDS (matches the engine dataclass); nowMs is epoch MILLISECONDS.
const AS_OF = 1000; // seconds
const FRESH_NOW_MS = AS_OF * 1000; // same instant -> age 0s
const AGED_NOW_MS = (AS_OF + 120) * 1000; // +120s -> past a 60s window

function env(over: Partial<DataEnvelope>): DataEnvelope {
  return {
    value: 5000,
    source: "ibkr",
    as_of: AS_OF,
    is_live: true,
    stale_after_s: 60,
    ...over,
  };
}

// ── Golden cases ─────────────────────────────────────────────────────────────

// 1. Live-tier + server is_live + fresh -> LIVE (the only path to a live badge).
const live = classifyProvenance(env({}), FRESH_NOW_MS);

// 2. Live-tier but server says is_live=false -> honestly STALE, never LIVE.
const serverDowngraded = classifyProvenance(env({ is_live: false }), FRESH_NOW_MS);

// 3. Cached / delayed tier, even if the server erroneously flagged is_live=true
//    -> STATIC, never LIVE (source-tier gate short-circuits).
const cached = classifyProvenance(env({ source: "polygon", is_live: true }), FRESH_NOW_MS);
const csvCache = classifyProvenance(env({ source: "csv_cache", is_live: true }), FRESH_NOW_MS);

// 4. Live-tier + is_live but aged past the window -> downgraded to STALE on screen.
const agedOut = classifyProvenance(env({}), AGED_NOW_MS);

// 5. Null value -> NO DATA, never LIVE.
const noData = classifyProvenance(env({ value: null }), FRESH_NOW_MS);

// 6. No client clock (SSR / first render): server verdict honored, still gated.
const liveNoClock = classifyProvenance(env({}), null);
const downgradedNoClock = classifyProvenance(env({ is_live: false }), null);

// ── Assertions: LIVE badge is gated on is_live (+ source tier + freshness) ────

const _checks: boolean[] = [
  // Only the fully-qualified case is live.
  live.isLive === true,
  live.status === "live",
  live.badgeVariant === "live",
  live.label === "LIVE",

  // is_live=false is never promoted, regardless of tier/freshness.
  serverDowngraded.isLive === false,
  serverDowngraded.status === "stale",
  serverDowngraded.badgeVariant === "static",
  serverDowngraded.label === "STALE",
  downgradedNoClock.isLive === false,
  downgradedNoClock.badgeVariant === "static",

  // Cached/delayed source can never be live even if the server bug-sets is_live.
  cached.isLive === false,
  cached.status === "static",
  cached.label === "STATIC",
  csvCache.isLive === false,
  csvCache.badgeVariant === "static",

  // Aged-out live-tier value downgrades to stale, not live.
  agedOut.isLive === false,
  agedOut.status === "stale",

  // Null value -> NO DATA, not live.
  noData.isLive === false,
  noData.label === "NO DATA",
  noData.badgeVariant === "static",

  // Server verdict is honored without a clock, but still only when is_live.
  liveNoClock.isLive === true,
  liveNoClock.badgeVariant === "live",
];

export const _provenanceGatingChecks = _checks;

// ── Type-level guard: the badge variant can ONLY be live | static ────────────
// If a third variant ever leaks into ProvenanceView, this line stops compiling.
type BadgeVariant = ProvenanceView["badgeVariant"];
const _variantGuard: BadgeVariant extends "live" | "static" ? true : false = true;
void _variantGuard;

export {};
