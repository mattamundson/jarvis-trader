// CT wall-clock helpers for the /tape feed. Source files carry "YYYY-MM-DD HH:MM" Central time
// strings; freshness needs epoch ms. DST-safe via Intl (no tz database dependency).
const TZ = "America/Chicago";

function tzOffsetMs(ms: number): number {
  const f = new Intl.DateTimeFormat("en-US", {
    timeZone: TZ, hour12: false, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  const p: Record<string, number> = {};
  for (const part of f.formatToParts(new Date(ms))) {
    if (part.type !== "literal") p[part.type] = Number(part.value);
  }
  const wall = Date.UTC(p.year, p.month - 1, p.day, p.hour % 24, p.minute, p.second);
  return wall - Math.floor(ms / 1000) * 1000;
}

/** "2026-10-26 14:59" (Central) -> epoch ms, or null when unparseable. */
export function ctWallToEpochMs(s: unknown): number | null {
  if (typeof s !== "string") return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/.exec(s.trim());
  if (!m) return null;
  const asUtc = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]), Number(m[6] ?? 0));
  let t = asUtc - tzOffsetMs(asUtc);
  t = asUtc - tzOffsetMs(t);
  return Number.isFinite(t) ? t : null;
}

export type FreshnessLevel = "fresh" | "amber" | "red" | "unknown";

/** amber at 2x the source's own interval, red at 5x. */
export function freshnessLevel(ageS: number | null, intervalS: number): FreshnessLevel {
  if (ageS == null || !Number.isFinite(ageS) || intervalS <= 0) return "unknown";
  if (ageS >= 5 * intervalS) return "red";
  if (ageS >= 2 * intervalS) return "amber";
  return "fresh";
}

export function fmtAge(ageS: number | null): string {
  if (ageS == null || !Number.isFinite(ageS)) return "no timestamp";
  const s = Math.max(0, Math.round(ageS));
  if (s < 90) return `${s}s`;
  if (s < 5400) return `${Math.round(s / 60)}m`;
  if (s < 172800) return `${(s / 3600).toFixed(1)}h`;
  return `${Math.round(s / 86400)}d`;
}
