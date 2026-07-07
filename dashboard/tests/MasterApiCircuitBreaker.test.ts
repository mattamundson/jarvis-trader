/**
 * P0.4 dashboard side — split-brain circuit-breaker contract (compile-time test).
 *
 * No runtime framework in this project (no Jest/Vitest); the dashboard convention
 * is type-level tests checked by tsc. Run via:
 *   cd dashboard && ./node_modules/.bin/tsc -p tsconfig.cbtest.json --noEmit
 *
 * Guards: master-api now signals freshness on /master/status. The dashboard must
 * trip an explicit "aggregation degraded" banner when EITHER the fetch failed
 * (master-api unreachable / crashlooping) OR the response reports
 * aggregation_ok === false (serving a cache that stopped refreshing) — instead of
 * silently rendering stale-but-trustworthy-looking numbers.
 */
import type { MasterStatus } from "../lib/masterApi";
import { aggregationBannerState } from "../lib/masterApi";

// The new freshness fields must exist on the type.
const fresh: MasterStatus = {
  domains: {},
  system_ok: true,
  ts: "2026-06-22T08:00:00+00:00",
  aggregation_ok: true,
  stale_domains: [],
};

const degraded: MasterStatus = {
  ...fresh,
  aggregation_ok: false,
  stale_domains: ["trading", "finances"],
};

const _checks: boolean[] = [
  // Healthy aggregate, fetch succeeded -> no banner.
  aggregationBannerState(fresh, false).degraded === false,
  // Server says stale -> banner, naming the stale domains in the reason.
  aggregationBannerState(degraded, false).degraded === true,
  aggregationBannerState(degraded, false).reason.includes("trading"),
  // Fetch failed (master-api down) even with no body -> banner.
  aggregationBannerState(null, true).degraded === true,
  // Null body but fetch not flagged failed is still degraded (no data to trust).
  aggregationBannerState(null, false).degraded === true,
];

export const _masterApiCircuitBreakerChecks = _checks;
