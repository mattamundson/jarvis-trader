/**
 * Shared SWR polling cadence for the dashboard. Hooks/widgets should reference
 * these named tiers instead of hardcoding a magic-number `refreshInterval`, so
 * polling frequency is decided in one place and stays consistent across the app.
 */
export const POLL_INTERVAL = {
  /** Highly time-sensitive integrity state. */
  REALTIME: 2_000,
  /** Pending human action surfaces. */
  APPROVALS: 3_000,
  /** Core health/status checks that gate offline & degraded-data banners. */
  HEALTH: 10_000,
  /** Fast-moving live trading data (positions, signals). */
  FAST: 5_000,
  /** Standard widget refresh. */
  NORMAL: 10_000,
  /** Operational status shared by Mission Control and trust surfaces. */
  STATUS: 15_000,
  /** Slow-changing summaries (backtests, settings, journal). */
  SLOW: 30_000,
  /** Rarely-changing aggregate data. */
  MINUTE: 60_000,
  /** Medium-weight reports and evidence snapshots. */
  TWO_MINUTES: 120_000,
  /** Market/research data whose providers already cache heavily. */
  FIVE_MINUTES: 300_000,
  /** Very slow knowledge aggregates. */
  HALF_HOUR: 30 * 60_000,
} as const;

export type PollInterval = (typeof POLL_INTERVAL)[keyof typeof POLL_INTERVAL];

const POLL_INTERVAL_BY_MS = new Map<number, PollInterval>(
  Object.values(POLL_INTERVAL).map((milliseconds) => [milliseconds, milliseconds]),
);

/** Resolves an existing cadence exactly; unknown values fail rather than becoming faster. */
export function pollingIntervalForMs(milliseconds: number): PollInterval {
  const interval = POLL_INTERVAL_BY_MS.get(milliseconds);
  if (interval === undefined) {
    throw new Error(`Unmapped polling interval: ${milliseconds}ms`);
  }
  return interval;
}

/** Shared SWR key for the `/health/full` payload, so every consumer of the
 * engine's full-health subsystems (IB gateway, LLM path, etc.) dedupes onto
 * ONE polled request instead of each hook issuing its own. */
export const HEALTH_FULL_KEY = "/health/full";
export const HEALTH_KEY = "/health";
export const POSITIONS_KEY = "/brokers/positions";
export const APPROVALS_KEY = "/pipeline/pending-approvals";
export const EXECUTION_STATE_KEY = "/safety/status";
