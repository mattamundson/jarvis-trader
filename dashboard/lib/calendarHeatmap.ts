// Pure month/calendar-grid helpers for CalendarHeatmap.
//
// Extracted (GT-33, same pattern as GT-30/PR #503's lib/weekDates.ts) so the
// hydration-guard mechanism can be unit-tested with node:test -- no JSX, no
// DOM required.

export interface CalendarMonthDisplay {
  year: number;
  month: number; // 0-indexed, JS Date convention
  monthLabel: string;
  cells: (number | null)[];
  todayDay: number;
}

/**
 * Builds the calendar grid (leading `null` filler cells + day-of-month
 * numbers, padded to complete the last week) for the month containing `now`.
 */
export function buildCalendarMonth(now: Date): CalendarMonthDisplay {
  const year = now.getFullYear();
  const month = now.getMonth();
  const monthLabel = now.toLocaleString("default", {
    month: "long",
    year: "numeric",
  });

  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const cells: (number | null)[] = Array<null>(firstDay).fill(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);

  return { year, month, monthLabel, cells, todayDay: now.getDate() };
}

/** "YYYY-MM-DD" for `day` within `year`/`month` (0-indexed month). */
export function calendarDateStr(year: number, month: number, day: number): string {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/**
 * Derives the calendar-grid display data from a client-only `today` value.
 *
 * `today` MUST be `null` until a mount-only `useEffect` sets it (see
 * CalendarHeatmap.tsx). Calling `new Date()` directly during render makes
 * SSR output (evaluated at server-render/build time) diverge from the
 * client's first hydration pass (evaluated whenever the browser actually
 * loads the page) whenever those two clock reads straddle a day/month
 * boundary -- producing a React #418 hydration mismatch on the month label,
 * the calendar grid, and the "is today" ring highlight.
 *
 * While `today` is `null` -- true for every server render and the client's
 * first hydration render, regardless of what wall-clock time either one
 * runs at -- this always returns `null`, so the server and the client's
 * first paint both take the loading-skeleton branch and can never disagree.
 * The real calendar only appears after mount.
 */
export function calendarDisplayFor(today: Date | null): CalendarMonthDisplay | null {
  return today ? buildCalendarMonth(today) : null;
}
