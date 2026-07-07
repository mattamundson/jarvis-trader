/**
 * Shared SWR polling cadence for the dashboard. Hooks/widgets should reference
 * these named tiers instead of hardcoding a magic-number `refreshInterval`, so
 * polling frequency is decided in one place and stays consistent across the app.
 */
export const POLL_INTERVAL = {
  /** Core health/status checks that gate offline & degraded-data banners. */
  HEALTH: 10_000,
  /** Fast-moving live trading data (positions, signals). */
  FAST: 5_000,
  /** Standard widget refresh. */
  NORMAL: 10_000,
  /** Slow-changing summaries (backtests, settings, journal). */
  SLOW: 30_000,
  /** Rarely-changing aggregate data. */
  MINUTE: 60_000,
} as const;

/** Shared SWR key for the `/health/full` payload, so every consumer of the
 * engine's full-health subsystems (IB gateway, LLM path, etc.) dedupes onto
 * ONE polled request instead of each hook issuing its own. */
export const HEALTH_FULL_KEY = "/health/full";
