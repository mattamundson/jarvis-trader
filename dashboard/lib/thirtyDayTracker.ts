// Pure day-window helpers for ThirtyDayTracker (GT-34, sibling fix to
// GT-27 PR #496 / GT-30 PR #503 / GT-33 PR #506).
//
// See ThirtyDayTracker in AnalyticsTab.tsx for the two hydration defects
// this closes:
//
//   1. The original `useState` lazy initializer branched on `typeof window`
//      directly inside the initializer function:
//        useState<Date>(() => typeof window !== "undefined" ? ... : ...)
//      `typeof window` is `"undefined"` on EVERY server render and
//      `"object"` on EVERY client render (the browser already has a
//      `window` by the time React hydrates) -- so the server branch and the
//      client's first-hydration branch are guaranteed to disagree on every
//      single render, not just across a clock boundary. This is strictly
//      worse than the unguarded-`new Date()` class fixed in GT-27/30/33.
//
//   2. `const today = new Date()` read directly during render is that
//      unguarded-`new Date()` class: SSR output is evaluated at
//      server-render/build time; the client's first hydration render is
//      evaluated whenever the browser actually loads the page (which can be
//      hours/days later for a statically-optimized route). Whenever those
//      two clock reads straddle a day boundary, the ELAPSED/REMAINING
//      tiles, the progress bar, and the calendar's "today" cell disagree
//      between server and client -> React error #418.
//
// Fix for both: `today` and `startDate` are client-only React state that
// start at `null` and are only ever set from a mount-only `useEffect` (see
// AnalyticsTab.tsx). Every function below is a pure function of those
// nullable inputs, so a server render and the client's pre-mount render
// both take the same placeholder branch and can never disagree. The real
// values fill in after mount, once both reads happen in the same browser
// session.

export const WINDOW_DAYS = 30;
export const START_DATE_STORAGE_KEY = "jarvis-paper-start-date";

function atMidnight(d: Date): Date {
  const out = new Date(d);
  out.setHours(0, 0, 0, 0);
  return out;
}

/** The 30-day-prior default start date, anchored to `today`, midnight-local. */
export function defaultStartDate(today: Date): Date {
  const out = atMidnight(today);
  out.setDate(out.getDate() - WINDOW_DAYS);
  return out;
}

/**
 * Resolves the initial start date from a (possibly null) localStorage
 * value, falling back to the 30-days-ago default. This is a pure function
 * of its two explicit arguments -- it never reads `window` or `localStorage`
 * itself, so it is safe to call unconditionally from either a "server"
 * context (pass `stored: null`) or a "client" context (pass the actual
 * stored string). Call it from a mount-only effect, never during render --
 * that ordering is the fix for defect #1 above.
 */
export function resolveStartDate(today: Date, stored: string | null): Date {
  if (stored) {
    const d = new Date(stored);
    if (!isNaN(d.getTime())) return d;
  }
  return defaultStartDate(today);
}

export interface TrackerStats {
  endDate: Date;
  daysElapsed: number;
  daysRemaining: number;
  progress: number;
}

/**
 * Derives elapsed/remaining/progress from a client-only `today`. Returns a
 * stable zero-progress placeholder when `today` is `null` (pre-mount / SSR)
 * so the server render and the client's first render always agree,
 * regardless of what wall-clock time either one runs at.
 */
export function trackerStatsFor(startDate: Date, today: Date | null): TrackerStats {
  const endDate = new Date(startDate);
  endDate.setDate(endDate.getDate() + WINDOW_DAYS);

  if (today === null) {
    return { endDate, daysElapsed: 0, daysRemaining: WINDOW_DAYS, progress: 0 };
  }

  const t = atMidnight(today);
  const elapsedMs = t.getTime() - startDate.getTime();
  const daysElapsed = Math.max(0, Math.min(WINDOW_DAYS, Math.floor(elapsedMs / 86400000)));
  const daysRemaining = Math.max(0, WINDOW_DAYS - daysElapsed);
  const progress = Math.min(100, (daysElapsed / WINDOW_DAYS) * 100);

  return { endDate, daysElapsed, daysRemaining, progress };
}

export type CalCellStatus = "before" | "active-past" | "today" | "future" | "outside";

export interface CalCell {
  date: Date;
  status: CalCellStatus;
}

/**
 * Builds the 5x7 (35-cell) calendar grid for the window starting at
 * `startDate`. When `today` is `null` (pre-mount / SSR) there is no live
 * "today" to compare against yet, so every on-window cell renders as
 * "future"/"outside" -- a stable placeholder shared by the server render
 * and the client's pre-mount render.
 */
export function buildCalendarCells(startDate: Date, endDate: Date, today: Date | null): CalCell[] {
  const dow = startDate.getDay();
  const gridStart = new Date(startDate);
  gridStart.setDate(gridStart.getDate() - dow);

  const t = today ? atMidnight(today) : null;

  const cells: CalCell[] = [];
  for (let i = 0; i < 35; i++) {
    const d = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    d.setHours(0, 0, 0, 0);

    if (d < startDate) {
      cells.push({ date: d, status: "before" });
    } else if (t !== null && d.getTime() === t.getTime()) {
      cells.push({ date: d, status: "today" });
    } else if (t !== null && d < t && d < endDate) {
      cells.push({ date: d, status: "active-past" });
    } else if (d >= endDate || (t !== null && d > t)) {
      cells.push({ date: d, status: d >= endDate ? "outside" : "future" });
    } else {
      cells.push({ date: d, status: "future" });
    }
  }
  return cells;
}
