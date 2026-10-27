// In-memory health check history (last 100 checks)
type HealthRecord = {
  timestamp: string;
  status: "live" | "stale" | "offline";
  age_seconds: number;
};

const history: HealthRecord[] = [];
const MAX_HISTORY = 100;

export function recordHealthCheck(record: HealthRecord) {
  history.push(record);
  if (history.length > MAX_HISTORY) {
    history.shift();
  }
}

export function getHealthHistory() {
  return history;
}

export function calculateUptime(windowMinutes: number = 60): number {
  const cutoff = Date.now() - windowMinutes * 60 * 1000;
  const recentChecks = history.filter(
    r => new Date(r.timestamp).getTime() > cutoff
  );
  
  if (recentChecks.length === 0) return 0;
  
  const liveCount = recentChecks.filter(r => r.status === "live").length;
  return (liveCount / recentChecks.length) * 100;
}
