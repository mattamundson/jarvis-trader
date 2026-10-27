// Structured logging for monitoring layer
export function logHealthCheck(data: {
  timestamp: string;
  status: "live" | "stale" | "offline";
  age_seconds: number;
  response_time_ms: number;
  source: "endpoint" | "cron";
}) {
  console.log(JSON.stringify({
    type: "health_check",
    ...data
  }));
}

export function logCronAlert(data: {
  timestamp: string;
  triggered: boolean;
  blob_age_seconds: number;
  discord_sent: boolean;
  discord_response_status?: number;
}) {
  console.log(JSON.stringify({
    type: "cron_alert",
    ...data
  }));
}
