"use client";

import { useEffect, useState } from "react";
import { fmtAge, freshnessLevel, type FreshnessLevel } from "@/lib/tape/time";
import { C, MONO } from "./theme";

/** Ticking clock corrected for server/browser skew so ages stay honest between 5s polls. */
export function useClockMs(serverNowMs: number | undefined): number {
  const [tick, setTick] = useState(0);
  const [skew, setSkew] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);
  useEffect(() => {
    if (serverNowMs) setSkew(serverNowMs - Date.now());
  }, [serverNowMs]);
  void tick;
  return Date.now() + skew;
}

export const LEVEL_COLOR: Record<FreshnessLevel, string> = {
  fresh: C.green, amber: C.amber, red: C.red, unknown: C.dim,
};

export function ageSeconds(asOfMs: number | null | undefined, nowMs: number): number | null {
  return asOfMs == null ? null : Math.max(0, (nowMs - asOfMs) / 1000);
}

export function FreshChip({ label, ageS, intervalS, testId }: { label: string; ageS: number | null; intervalS: number; testId?: string }) {
  const level = freshnessLevel(ageS, intervalS);
  const color = LEVEL_COLOR[level];
  return (
    <span
      data-testid={testId}
      data-level={level}
      title={`${label}: expected every ${intervalS}s; amber at 2x, red at 5x`}
      className={`inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-0.5 text-[10px] leading-none ${MONO}`}
      style={{ borderColor: color, color }}
    >
      <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {label} {fmtAge(ageS)}
    </span>
  );
}

export function StaleBanner({ level, ageS, asOf, present, what }: { level: FreshnessLevel; ageS: number | null; asOf?: string | null; present: boolean; what: string }) {
  if (present && level !== "red" && level !== "unknown") return null;
  const text = !present
    ? `NO DATA: ${what} has not been written yet.`
    : level === "unknown"
      ? `NO TIMESTAMP: cannot tell how old this ${what} is.`
      : `STALE: last update ${fmtAge(ageS)} ago${asOf ? ` (as of ${asOf} CT)` : ""}. Levels may not reflect current structure.`;
  return (
    <div data-testid="stale-banner" className="mb-2 border px-2 py-1 text-[10px] font-semibold uppercase tracking-wide"
      style={{ borderColor: C.red, color: C.red, background: "rgba(248,81,73,0.08)" }}>
      {text}
    </div>
  );
}
