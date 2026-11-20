import { NextResponse } from "next/server";
import { getHealthHistory, calculateUptime } from "@/lib/healthHistory";

export async function GET() {
  const history = getHealthHistory();
  const uptime1h = calculateUptime(60);
  const uptime24h = calculateUptime(1440);
  
  const now = history[history.length - 1];
  
  return NextResponse.json({
    current_status: now?.status || "unknown",
    current_age_seconds: now?.age_seconds || null,
    uptime_1h_pct: uptime1h.toFixed(2),
    uptime_24h_pct: uptime24h.toFixed(2),
    checks_recorded: history.length,
    last_check: now?.timestamp || null
  });
}
