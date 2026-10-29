import { NextResponse } from "next/server";
import { sendAlert } from "@/lib/alerting";

// Vercel KV store for last watchdog check timestamp
// (If KV not available, degrade to in-memory with warning)
let lastWatchdogCheck: number = Date.now();

export async function GET(request: Request) {
  const authHeader = request.headers.get("authorization");
  if (authHeader !== `Bearer ${process.env.CRON_SECRET}`) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  
  const now = Date.now();
  const elapsedMinutes = Math.floor((now - lastWatchdogCheck) / 60000);
  
  // Watchdog should check every 5 minutes
  // Alert if > 10 minutes (2x expected + buffer)
  if (elapsedMinutes > 10) {
    await sendAlert(
      `⚠️ **Watchdog Health Alert**\n\n` +
      `Watchdog last checked **${elapsedMinutes} minutes ago**.\n\n` +
      `Expected: every 5 minutes.\n` +
      `Check Windows Task Scheduler on Matt's PC.`
    );
    
    console.error(`[watchdog-health] Watchdog silent for ${elapsedMinutes} min`);
    
    return NextResponse.json({ 
      status: "watchdog_silent", 
      elapsed_minutes: elapsedMinutes,
      last_check: new Date(lastWatchdogCheck).toISOString()
    });
  }
  
  console.log(`[watchdog-health] Watchdog healthy (${elapsedMinutes} min since last check)`);
  
  return NextResponse.json({ 
    status: "healthy",
    elapsed_minutes: elapsedMinutes,
    last_check: new Date(lastWatchdogCheck).toISOString()
  });
}

// Health endpoint for watchdog to ping
export async function POST(request: Request) {
  const apiKey = request.headers.get("x-api-key");
  
  if (apiKey !== process.env.API_KEY) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  
  lastWatchdogCheck = Date.now();
  console.log("[watchdog-health] Watchdog heartbeat received");
  
  return NextResponse.json({ 
    status: "acknowledged",
    timestamp: new Date().toISOString()
  });
}
