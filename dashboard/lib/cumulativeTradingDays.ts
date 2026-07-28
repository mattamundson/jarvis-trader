// Pure date/pace helpers for CumulativeTradingDaysWidget.
//
// Extracted (GT-33, same pattern as GT-27/PR #496 on DailyPnLCalendarWidget
// and GT-30/PR #503's lib/weekDates.ts on WeeklyPnLCard) so the
// hydration-guard mechanism can be unit-tested with node:test -- no JSX, no
// DOM required.

export const TARGET_TRADING_DAYS = 30;

export function addDays(d: Date, n: number): Date {
  const result = new Date(d);
  result.setDate(result.getDate() + n);
  return result;
}

export function toDateStr(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function formatEstDate(d: Date): string {
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export interface ActivityDot {
  dateStr: string;
  hasTraded: boolean;
}

export interface TradingDaysDisplay {
  daysSinceFirst: number;
  pace: number;
  estCompletionLabel: string;
  activityDots: ActivityDot[];
}

/**
 * Derives the pace / ETA / 30-day-activity-grid display data from a
 * client-only `today` value.
 *
 * `today` MUST be `null` until a mount-only `useEffect` sets it (see
 * CumulativeTradingDaysWidget.tsx). Computing `new Date()` directly during
 * render makes SSR output (evaluated at server-render/build time) diverge
 * from the client's first hydration pass (evaluated whenever the browser
 * actually loads the page -- which can be hours/days later for a
 * statically-optimized route) whenever those two clock reads straddle a day
 * boundary -- shifting the "Est. completion" date label and every dot's
 * date (and therefore its key/tooltip/traded-state) in the 30-day activity
 * grid -- producing a React #418 hydration mismatch.
 *
 * While `today` is `null` -- true for every server render and the client's
 * first hydration render, regardless of what wall-clock time either one
 * runs at -- this always returns the same empty placeholder, so the server
 * and the client's first paint can never disagree. The real values only
 * appear after mount.
 */
export function computeTradingDaysDisplay(
  today: Date | null,
  tradingDays: number,
  firstTradeDateStr: string | null,
  tradingDaySet: Set<string>,
  targetDays: number = TARGET_TRADING_DAYS
): TradingDaysDisplay {
  if (!today) {
    return { daysSinceFirst: 0, pace: 0, estCompletionLabel: "", activityDots: [] };
  }

  let pace = 0;
  let daysSinceFirst = 0;
  if (firstTradeDateStr) {
    const firstDate = new Date(firstTradeDateStr + "T00:00:00");
    daysSinceFirst = Math.max(
      1,
      Math.floor((today.getTime() - firstDate.getTime()) / (1000 * 60 * 60 * 24)) + 1
    );
    pace = tradingDays / daysSinceFirst;
  }

  const daysRemaining = Math.max(0, targetDays - tradingDays);
  let estCompletionLabel = "Insufficient data";
  if (tradingDays >= targetDays) {
    estCompletionLabel = "Target met!";
  } else if (pace > 0) {
    const calendarDaysNeeded = Math.ceil(daysRemaining / pace);
    const estDate = addDays(today, calendarDaysNeeded);
    estCompletionLabel = `Est. completion: ${formatEstDate(estDate)}`;
  }

  const activityDots: ActivityDot[] = [];
  for (let i = 29; i >= 0; i--) {
    const d = addDays(today, -i);
    const dateStr = toDateStr(d);
    activityDots.push({ dateStr, hasTraded: tradingDaySet.has(dateStr) });
  }

  return { daysSinceFirst, pace, estCompletionLabel, activityDots };
}
