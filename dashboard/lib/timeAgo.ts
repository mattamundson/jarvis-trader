// Pure relative-time helper for ApprovalPanel.
//
// GT-33 judgment call: unlike the other 4 components in this audit,
// ApprovalPanel does NOT get the full client-only useState<Date|null> +
// useEffect hydration guard (GT-27/GT-30 pattern). Its only caller of
// timeAgo() is inside the `pending.map(...)` branch, which is gated behind
// useSWR's `isLoading`/`data` readiness (see ApprovalPanel.tsx). useSWR
// returns `data: undefined, isLoading: true` on both the server render AND
// the client's first (pre-fetch) hydration render, so both always take the
// loading-skeleton branch -- never the timeAgo() branch -- until the fetch
// resolves client-side, well after hydration has already completed. There
// is no server-rendered/first-hydration-render output for React to compare
// against, so a minute/hour boundary crossing during that gap cannot
// produce a #418 mismatch. `ExpiryTimer`'s `new Date()` call is likewise
// already safe: it only runs inside a `useEffect`, never during render.
//
// `now` is still threaded through as a parameter (rather than read
// internally via `new Date()`) purely so this stays unit-testable without
// faking the system clock -- not because a hydration guard is needed here.

/** Formats an ISO timestamp as "just now" / "Xm ago" / "Xh ago" relative to `now`. */
export function timeAgo(isoString: string, now: Date): string {
  const then = new Date(isoString);
  const diffMs = now.getTime() - then.getTime();
  const diffMins = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMins / 60);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return isoString;
}
