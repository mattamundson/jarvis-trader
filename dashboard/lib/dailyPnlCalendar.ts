// Pure date helpers for DailyPnLCalendarWidget.
//
// Extracted (GT-33). DailyPnLCalendarWidget is GT-27's own target: PR #496
// (still open/unmerged as of this fix) adds the client-only guard directly
// in the component without a lib/ extraction. This GT-33 pass instead
// follows GT-30/PR #503's more thorough lib/weekDates.ts convention so the
// hydration-guard mechanism can be unit-tested with node:test -- no JSX, no
// DOM required.
//
// NOTE: because PR #496 also touches this exact component file (with a
// non-extracted version of the same guard), whichever of #496 / this GT-33
// branch merges second will need manual reconciliation (conflict or
// duplicate-guard cleanup) rather than a clean merge. Expected, not a bug --
// see the GT-33 PR description.

/**
 * Mon-Fri dates spanning the past 30 calendar days (29 days ago through
 * `today`, inclusive).
 */
export function buildCalendarDays(today: Date): Date[] {
  const days: Date[] = [];
  const start = new Date(today);
  start.setHours(0, 0, 0, 0);
  for (let i = 29; i >= 0; i--) {
    const d = new Date(start);
    d.setDate(start.getDate() - i);
    const dow = d.getDay(); // 0=Sun, 6=Sat
    if (dow >= 1 && dow <= 5) {
      days.push(d);
    }
  }
  return days;
}

export function toYMD(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}

export interface DailyPnLCalendarDisplay {
  calDays: Date[];
  todayStr: string;
  monthLabel: string;
}

/**
 * Derives the 30-day calendar grid display data from a client-only `today`
 * value.
 *
 * `today` MUST be `null` until a mount-only `useEffect` sets it (see
 * DailyPnLCalendarWidget.tsx). Calling `new Date()` directly during render
 * makes SSR output (evaluated at server-render/build time) diverge from the
 * client's first hydration pass (evaluated whenever the browser actually
 * loads the page) whenever those two clock reads straddle a day/month
 * boundary -- producing a React #418 hydration mismatch on the month label,
 * the day grid, and the "is today" cell highlight.
 *
 * While `today` is `null` -- true for every server render and the client's
 * first hydration render, regardless of what wall-clock time either one
 * runs at -- this always returns the same empty placeholder (which the
 * component's existing `calDays.length === 0` empty-state branch already
 * renders identically), so the server and the client's first paint can
 * never disagree. The real calendar fills in client-side after mount.
 */
export function dailyPnlCalendarDisplayFor(today: Date | null): DailyPnLCalendarDisplay {
  if (!today) {
    return { calDays: [], todayStr: "", monthLabel: "" };
  }
  return {
    calDays: buildCalendarDays(today),
    todayStr: toYMD(today),
    monthLabel: today.toLocaleDateString("en-US", { month: "long", year: "numeric" }),
  };
}
