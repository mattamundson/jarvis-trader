// Helper functions for the /ops page

// Mask account ID to last 4 digits
export function maskAccountId(accountId: string): string {
  if (!accountId || accountId.length <= 4) {
    return accountId;
  }
  return `***${accountId.slice(-4)}`;
}

// Format currency without dollar sign (requirement: never render dollar amounts)
export function formatNumber(value: number): string {
  return value.toFixed(2);
}

// Calculate proof bar progress percentage
export function calculateProofBarProgress(
  cleanSessions: number,
  scoredSetups: number
): number {
  const sessionProgress = Math.min(cleanSessions / 10, 1) * 50;
  const setupProgress = Math.min(scoredSetups / 20, 1) * 50;
  return Math.round(sessionProgress + setupProgress);
}

// Format timestamp for display
export function formatTimestamp(iso: string): string {
  try {
    const date = new Date(iso);
    if (isNaN(date.getTime())) {
      return iso;
    }
    return date.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return iso;
  }
}

// Calculate age in seconds from ISO timestamp
export function calculateAgeSeconds(iso: string): number {
  try {
    const date = new Date(iso);
    if (isNaN(date.getTime())) {
      return -1;
    }
    return Math.floor((Date.now() - date.getTime()) / 1000);
  } catch {
    return -1;
  }
}

// Format seconds to human-readable duration
export function formatDuration(seconds: number): string {
  if (seconds < 0) return "unknown";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}m ${s}s`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}
