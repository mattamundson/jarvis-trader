/** Pure readout freshness rules: file writes/copies never renew market evidence. */
const nonnegative = (v: unknown): number | null =>
  typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : null;

export function tapeEvaluationAllowed(
  hasSnapshot: boolean, snapshotAge: number | null, tickAge: number | null,
  fetchFailed: boolean, threshold = 60,
): boolean {
  return hasSnapshot && !fetchFailed && nonnegative(snapshotAge) !== null &&
    nonnegative(tickAge) !== null && snapshotAge! <= threshold && tickAge! <= threshold;
}

export function recorderContext(raw: any, serverEpochMs: number) {
  const r = raw?.recorder && typeof raw.recorder === 'object' ? raw.recorder : {};
  // Ages were measured when the producer wrote as_of_epoch, NOT when a copy
  // touched the file mtime. Unknown/future source clocks must remain unknown.
  const source = nonnegative(raw?.as_of_epoch);
  const elapsed = source === null ? null : nonnegative(serverEpochMs / 1000 - source);
  const age = (value: unknown) => {
    const v = nonnegative(value);
    return v === null || elapsed === null ? null : Math.round((v + elapsed) * 10) / 10;
  };
  return {
    state: typeof r.state === 'string' ? r.state : null,
    heartbeatAgeS: age(r.heartbeat_age_s), lastTickAgeS: age(r.last_tick_age_s),
    reconnects: nonnegative(r.reconnects), connectedPort: nonnegative(r.connected_port),
    sessionTradingDay: typeof raw?.session?.trading_day === 'string' ? raw.session.trading_day : null,
    levelsSource: typeof raw?.levels_source === 'string' ? raw.levels_source : null,
  };
}
