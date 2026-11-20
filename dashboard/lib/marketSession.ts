/**
 * Explicit known-market-state contract for ES/MES Globex hours (readout only).
 *
 * The /tape screen may assert "market closed" ONLY from this schedule contract, never from
 * recorder idleness alone (an idle recorder can mean feed loss during an open market).
 * Basis: CME ES product overview weekly trading hours — Sunday 17:00 CT to Friday 16:00 CT,
 * with a daily trading break 16:00-17:00 CT. CME holiday calendars are NOT accounted here:
 * inside a scheduled-open window the honest label is "scheduled open (holidays not accounted)".
 */

export type EsMarketState = "scheduled_open" | "scheduled_closed" | "unknown";

export interface MarketStateInfo {
  state: EsMarketState;
  /** One-line explanation rendered on the page; states which window of the schedule applies. */
  detail: string;
  /** The contract this assertion is derived from. Never "recorder idle". */
  basis: "cme-globex-schedule";
}

export const ES_SCHEDULE_BASIS =
  "CME ES Globex schedule: Sun 17:00 - Fri 16:00 CT, daily break 16:00-17:00 CT; holidays not accounted";

function chicagoParts(epochMs: number): Record<string, number> | null {
  if (!Number.isFinite(epochMs)) return null;
  const f = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago",
    weekday: "short",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const o: Record<string, number> = {};
  let wd = "";
  for (const p of f.formatToParts(new Date(epochMs))) {
    if (p.type === "weekday") wd = p.value;
    else if (p.type !== "literal") o[p.type] = Number(p.value);
  }
  const WD: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  const weekday = WD[wd];
  if (weekday === undefined) return null;
  if (o.hour === 24) o.hour = 0;
  o.weekday = weekday;
  return o;
}

/** Classify `nowMs` against the published Globex weekly schedule. Never asserts from idleness. */
export function esMarketState(nowMs: number): MarketStateInfo {
  const p = chicagoParts(nowMs);
  if (!p) {
    return { state: "unknown", detail: "clock unavailable — market state not asserted", basis: "cme-globex-schedule" };
  }
  const min = p.hour * 60 + p.minute;
  const wd = p.weekday as number;
  if (wd === 6) {
    return { state: "scheduled_closed", detail: "Saturday — weekend (weekly close Fri 16:00 CT)", basis: "cme-globex-schedule" };
  }
  if (wd === 0) {
    if (min < 17 * 60) {
      return { state: "scheduled_closed", detail: "Sunday before the 17:00 CT weekly open", basis: "cme-globex-schedule" };
    }
    return { state: "scheduled_open", detail: `Sunday evening Globex session (${ES_SCHEDULE_BASIS})`, basis: "cme-globex-schedule" };
  }
  if (wd === 5) {
    if (min < 16 * 60) {
      return { state: "scheduled_open", detail: `Friday session until 16:00 CT (${ES_SCHEDULE_BASIS})`, basis: "cme-globex-schedule" };
    }
    return { state: "scheduled_closed", detail: "after the Friday 16:00 CT close — weekend", basis: "cme-globex-schedule" };
  }
  // Mon-Thu
  if (min >= 16 * 60 && min < 17 * 60) {
    return { state: "scheduled_closed", detail: "daily maintenance break 16:00-17:00 CT", basis: "cme-globex-schedule" };
  }
  return { state: "scheduled_open", detail: `weekday Globex session (${ES_SCHEDULE_BASIS})`, basis: "cme-globex-schedule" };
}

/**
 * The Globex trading date a plan file must carry to count as the current session's plan:
 * the CT calendar date, rolled to the next day at 17:00 CT (the Sunday-evening open already
 * belongs to Monday's trading day, and Mon-Fri 17:00 belongs to the next day's session).
 */
export function currentGlobexTradingDate(nowMs: number): string | null {
  const p = chicagoParts(nowMs);
  if (!p) return null;
  const min = p.hour * 60 + p.minute;
  const nextDay = min >= 17 * 60 ? 1 : 0;
  const f = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Chicago",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return f.format(new Date(nowMs + nextDay * 86400_000));
}
