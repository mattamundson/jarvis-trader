// Shared pure relative-time helper for operational dashboard surfaces.
// `now` is explicit so callers control the clock and tests need no fake timers.

export interface RelativeTimeDisplay {
  text: string;
  state: "past" | "near-now" | "clock-skew" | "invalid";
}

function compactDuration(milliseconds: number): string {
  const seconds = Math.floor(milliseconds / 1_000);
  if (seconds < 60) return `${seconds}s`;

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;

  return `${Math.floor(hours / 24)}d`;
}

/** Classifies and formats an ISO timestamp relative to an explicit clock. */
export function relativeTime(
  isoString: string | null | undefined,
  now: Date,
): RelativeTimeDisplay {
  if (!isoString) return { text: "unknown time", state: "invalid" };

  const thenMs = new Date(isoString).getTime();
  const nowMs = now.getTime();
  if (!Number.isFinite(thenMs) || !Number.isFinite(nowMs)) {
    return { text: "unknown time", state: "invalid" };
  }

  const diffMs = nowMs - thenMs;
  if (diffMs < -60_000) {
    return {
      text: `clock skew (+${compactDuration(Math.abs(diffMs))})`,
      state: "clock-skew",
    };
  }

  if (diffMs < 60_000) return { text: "just now", state: "near-now" };
  return { text: `${compactDuration(diffMs)} ago`, state: "past" };
}

/** Compatibility formatter for existing consumers. */
export function timeAgo(isoString: string, now: Date): string {
  return relativeTime(isoString, now).text;
}
