export type FreshnessState = "LIVE" | "DELAYED" | "STALE" | "SAMPLE_DATA";

export interface FreshnessConfig {
  source: string;
  dataTimestamp: string | Date;
  isFixture?: boolean;
  stalenessThresholdMs?: number;
}

export interface FreshnessResult {
  state: FreshnessState;
  ageSeconds: number;
  source: string;
  asOfCT: string;
}

const CT_OFFSET_MS = -6 * 60 * 60 * 1000;

function toCentralTime(date: Date): string {
  const ctDate = new Date(date.getTime() + CT_OFFSET_MS);
  return ctDate.toLocaleTimeString("en-US", {
    timeZone: "UTC",
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function classifyFreshness(config: FreshnessConfig): FreshnessResult {
  const { source, dataTimestamp, isFixture, stalenessThresholdMs = 120_000 } = config;

  if (isFixture) {
    const ts = typeof dataTimestamp === "string" ? new Date(dataTimestamp) : dataTimestamp;
    return {
      state: "SAMPLE_DATA",
      ageSeconds: 0,
      source,
      asOfCT: ts.toLocaleDateString("en-US"),
    };
  }

  const ts = typeof dataTimestamp === "string" ? new Date(dataTimestamp) : dataTimestamp;
  const now = Date.now();
  const ageMs = now - ts.getTime();
  const ageSeconds = Math.floor(ageMs / 1000);

  const asOfCT = toCentralTime(ts);

  if (ageMs < 10_000) {
    return { state: "LIVE", ageSeconds, source, asOfCT };
  }

  if (ageMs < stalenessThresholdMs) {
    return { state: "DELAYED", ageSeconds, source, asOfCT };
  }

  return { state: "STALE", ageSeconds, source, asOfCT };
}

export function isMarketHours(date: Date = new Date()): boolean {
  const ctDate = new Date(date.getTime() + CT_OFFSET_MS);
  const day = ctDate.getUTCDay();
  const hour = ctDate.getUTCHours();
  const minute = ctDate.getUTCMinutes();
  
  if (day === 0 || day === 6) return false;
  
  const timeInMinutes = hour * 60 + minute;
  const marketOpen = 8 * 60 + 30;
  const marketClose = 15 * 60;
  
  return timeInMinutes >= marketOpen && timeInMinutes < marketClose;
}

export function getRTHStalenessThreshold(): number {
  return isMarketHours() ? 2 * 60 * 1000 : 120 * 60 * 1000;
}
