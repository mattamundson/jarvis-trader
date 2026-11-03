import type { FlowSnapshot } from "@/lib/flowTypes";

/** Pure freshness helpers for the flow snapshot. No I/O, safe in client and server code. */

function tsMs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  return Number.isFinite(t) ? t : null;
}

/**
 * Choose between the Vercel Blob snapshot and the live feed snapshot.
 * The newest `ts` wins, so an old pushed blob can never mask a live feed.
 * A snapshot with an unparsable ts loses to one with a valid ts.
 * Ties go to the feed (it is the live source). Returns null when neither exists.
 */
export function pickFreshest(
  blob: FlowSnapshot | null,
  feed: FlowSnapshot | null,
): { snapshot: FlowSnapshot; source: "blob" | "feed" } | null {
  if (blob && !feed) return { snapshot: blob, source: "blob" };
  if (feed && !blob) return { snapshot: feed, source: "feed" };
  if (!blob || !feed) return null;
  const b = tsMs(blob.ts);
  const f = tsMs(feed.ts);
  if (b !== null && (f === null || b > f)) return { snapshot: blob, source: "blob" };
  return { snapshot: feed, source: "feed" };
}

export interface NqFreshness {
  /** True when the NQ numbers must not be read as live. */
  stale: boolean;
  /** True when the numbers are the built-in placeholder fixture. */
  fixture: boolean;
  /** When the NQ numbers were read (sources.nq.asOf, else snapshot ts). */
  asOf: string | null;
  /** Age in whole seconds, null when asOf is missing or unparsable. */
  ageSeconds: number | null;
}

export const NQ_STALE_AFTER_MS = 120_000;

export function nqFreshness(
  flow: Pick<FlowSnapshot, "ts" | "fixture"> & { sources?: { nq?: { asOf?: string | null } | null } | null },
  nowMs: number,
  thresholdMs: number = NQ_STALE_AFTER_MS,
): NqFreshness {
  const asOf = flow.sources?.nq?.asOf ?? flow.ts ?? null;
  const t = tsMs(asOf);
  const ageSeconds = t === null ? null : Math.max(0, Math.round((nowMs - t) / 1000));
  const fixture = flow.fixture === true;
  const stale = fixture || ageSeconds === null || ageSeconds * 1000 > thresholdMs;
  return { stale, fixture, asOf, ageSeconds };
}

export function fmtAge(seconds: number | null): string {
  if (seconds === null) return "age unknown";
  if (seconds < 90) return `${seconds}s old`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m old`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)}h old`;
  return `${Math.round(seconds / 86400)}d old`;
}