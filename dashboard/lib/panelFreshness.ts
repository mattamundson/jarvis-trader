/**
 * Pure helpers for per-panel pull-time + stale warnings.
 * Addition-only: widgets pass `pulledAt` into CardHeader / PanelPullTime.
 * America/Chicago clock for operator-facing absolute times.
 */

export type FreshnessLevel = "live" | "delayed" | "stale" | "missing";

export const DEFAULT_FRESH_MS = 60_000;
export const DEFAULT_STALE_MS = 300_000;

export function toDate(value: Date | string | number | null | undefined): Date | null {
  if (value === null || value === undefined) return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function ageMs(pulledAt: Date | string | number | null | undefined, now: Date | number = Date.now()): number | null {
  const d = toDate(pulledAt);
  if (!d) return null;
  const n = typeof now === "number" ? now : now.getTime();
  return Math.max(0, n - d.getTime());
}

export function freshnessLevel(
  pulledAt: Date | string | number | null | undefined,
  opts: { freshMs?: number; staleMs?: number; now?: Date | number } = {},
): FreshnessLevel {
  const age = ageMs(pulledAt, opts.now ?? Date.now());
  if (age === null) return "missing";
  const freshMs = opts.freshMs ?? DEFAULT_FRESH_MS;
  const staleMs = opts.staleMs ?? DEFAULT_STALE_MS;
  if (age < freshMs) return "live";
  if (age < staleMs) return "delayed";
  return "stale";
}

/** Absolute pull clock in America/Chicago, HH:MM:SS CT. */
export function formatPullTimeCt(
  pulledAt: Date | string | number | null | undefined,
  now: Date | number = Date.now(),
): string {
  const d = toDate(pulledAt);
  if (!d) return "—";
  void now; // reserved for future relative formatting parity
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "00";
  return `${get("hour")}:${get("minute")}:${get("second")} CT`;
}

export function staleWarning(
  pulledAt: Date | string | number | null | undefined,
  opts: { freshMs?: number; staleMs?: number; now?: Date | number } = {},
): string | null {
  const level = freshnessLevel(pulledAt, opts);
  if (level === "missing") return "No pull time — data freshness unknown";
  if (level === "stale") return "Stale — treat levels as unreliable until refresh";
  return null;
}
