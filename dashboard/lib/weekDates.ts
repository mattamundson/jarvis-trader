// Pure week-date helpers for WeeklyPnLCard.
//
// Extracted out of the component (GT-30, sibling fix to GT-27 / PR #496 on
// DailyPnLCalendarWidget) so the hydration-guard mechanism can be unit-tested
// with node:test -- no JSX, no DOM required.

/** Mon-Fri ISO date strings ("YYYY-MM-DD") for the week containing `now`. */
export function getThisWeekDates(now: Date): string[] {
  const day = now.getDay(); // 0=Sun
  const monday = new Date(now);
  monday.setDate(now.getDate() - (day === 0 ? 6 : day - 1));
  return Array.from({ length: 5 }, (_, i) => {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    return d.toISOString().slice(0, 10);
  });
}

export interface WeekDisplay {
  weekDates: string[];
  mondayDate: string;
}

/**
 * Derives the week's display data from a client-only `today` value.
 *
 * `today` MUST be `null` until a mount-only `useEffect` sets it (see
 * WeeklyPnLCard.tsx). Calling `new Date()` directly during render makes SSR
 * output (evaluated at server-render/build time) diverge from the client's
 * first hydration pass (evaluated whenever the browser actually loads the
 * page -- which can be hours/days later for a statically-optimized route)
 * whenever those two clock reads straddle a day/week boundary -- e.g.
 * "Week of 2026-07-27" rendered server-side just before a Monday rollover vs
 * "Week of 2026-08-03" hydrated client-side just after -- producing a React
 * #418 hydration mismatch on the "Week of ..." text and the day grid.
 *
 * While `today` is `null` -- true for every server render and for the
 * client's first hydration render, regardless of what wall-clock time either
 * one runs at -- this always returns the same placeholder, so the server and
 * the client's first paint can never disagree. The real dates only appear
 * after mount, once both reads happen in the same browser session.
 */
export function weekDisplayFor(today: Date | null): WeekDisplay {
  const weekDates = today ? getThisWeekDates(today) : [];
  return { weekDates, mondayDate: weekDates[0] ?? "" };
}
