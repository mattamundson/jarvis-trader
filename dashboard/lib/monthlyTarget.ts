// Pure month helpers for MonthlyTargetCard.
//
// Extracted (GT-33, same pattern as GT-30/PR #503's lib/weekDates.ts) so the
// hydration-guard mechanism can be unit-tested with node:test -- no JSX, no
// DOM required.

/** "YYYY-MM" for the month containing `now`. */
export function getCurrentYearMonth(now: Date): string {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  return `${year}-${month}`;
}

/** e.g. "July 2026" for the month containing `now`. */
export function getMonthLabel(now: Date): string {
  return now.toLocaleString("en-US", { month: "long", year: "numeric" });
}

export interface MonthDisplay {
  yearMonth: string;
  monthLabel: string;
}

/**
 * Derives the current-month display data from a client-only `today` value.
 *
 * `today` MUST be `null` until a mount-only `useEffect` sets it (see
 * MonthlyTargetCard.tsx). Calling `new Date()` directly during render makes
 * SSR output (evaluated at server-render/build time) diverge from the
 * client's first hydration pass (evaluated whenever the browser actually
 * loads the page -- which can be hours/days later for a
 * statically-optimized route) whenever those two clock reads straddle a
 * month boundary -- e.g. a July-31 server render vs an August-1 client
 * hydration render would disagree on both which entries count toward "this
 * month" (`yearMonth`) and the "Month Year" label text -- producing a React
 * #418 hydration mismatch.
 *
 * While `today` is `null` -- true for every server render and the client's
 * first hydration render, regardless of what wall-clock time either one
 * runs at -- this always returns the same empty placeholder, so the server
 * and the client's first paint can never disagree. The real month fills in
 * client-side after mount.
 */
export function monthDisplayFor(today: Date | null): MonthDisplay {
  if (!today) return { yearMonth: "", monthLabel: "" };
  return { yearMonth: getCurrentYearMonth(today), monthLabel: getMonthLabel(today) };
}
