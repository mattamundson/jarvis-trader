import { NextResponse } from "next/server";
import { head } from "@vercel/blob";
import { logCronAlert, logHealthCheck } from "@/lib/healthLogger";
import { recordHealthCheck } from "@/lib/healthHistory";
import { sendAlert } from "@/lib/alerting";
import { logCronInvocation } from "@/lib/auditLog";

export async function GET(request: Request) {
  const ip = request.headers.get("x-forwarded-for")?.split(",")[0] || "unknown";
  const authHeader = request.headers.get("authorization");
  
  const authorized = authHeader === `Bearer ${process.env.CRON_SECRET}`;
  logCronInvocation(ip, "/api/cron/check-flow", authorized);
  
  if (!authorized) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const blobToken = process.env.BLOB_READ_WRITE_TOKEN;
  
  if (!blobToken) {
    return NextResponse.json({ 
      error: "BLOB_READ_WRITE_TOKEN not configured"
    }, { status: 503 });
  }

  try {
    const blob = await head("flow/latest.json", { token: blobToken });
    const ageMs = Date.now() - new Date(blob.uploadedAt).getTime();
    const ageMin = Math.floor(ageMs / 60000);
    const ageSec = Math.floor(ageMs / 1000);
    const timestamp = new Date().toISOString();
    
    // Determine status for health history
    let status: "live" | "stale" | "offline";
    if (ageSec < 10) status = "live";
    else if (ageSec < 120) status = "stale";
    else status = "offline";
    
    // Log health check from cron
    logHealthCheck({
      timestamp,
      status,
      age_seconds: ageSec,
      response_time_ms: 0,
      source: "cron"
    });
    
    // Record in history
    recordHealthCheck({
      timestamp,
      status,
      age_seconds: ageSec
    });
    
    if (ageMin > 5) {
      // Send alert via multi-channel system (Discord primary, email fallback)
      const alertResult = await sendAlert(
        `🔴 **Flow Feed STALE**\n\nLast update: **${ageMin} minutes ago**\n\nCheck Windows pusher.`
      );
      
      // Log alert event
      logCronAlert({
        timestamp,
        triggered: true,
        blob_age_seconds: ageSec,
        discord_sent: alertResult.channel === "discord",
        discord_response_status: alertResult.success ? 200 : 0
      });
      
      return NextResponse.json({ 
        status: "alerted", 
        age_minutes: ageMin,
        alert_channel: alertResult.channel,
        alert_success: alertResult.success
      });
    }
    
    // Log healthy check (no alert)
    logCronAlert({
      timestamp,
      triggered: false,
      blob_age_seconds: ageSec,
      discord_sent: false
    });
    
    return NextResponse.json({ status: "healthy", age_minutes: ageMin });
  } catch (err) {
    const timestamp = new Date().toISOString();
    
    // Record offline status
    logHealthCheck({
      timestamp,
      status: "offline",
      age_seconds: -1,
      response_time_ms: 0,
      source: "cron"
    });
    
    recordHealthCheck({
      timestamp,
      status: "offline",
      age_seconds: -1
    });
    
    // Send offline alert via multi-channel system
    const alertResult = await sendAlert(
      `🔴 **Flow Feed OFFLINE**\n\nBlob unreachable.\n\nError: \`${String(err).slice(0, 200)}\``
    );
    
    // Log offline alert
    logCronAlert({
      timestamp,
      triggered: true,
      blob_age_seconds: -1,
      discord_sent: alertResult.channel === "discord",
      discord_response_status: alertResult.success ? 200 : 0
    });
    
    return NextResponse.json({ 
      status: "error", 
      error: String(err),
      alert_channel: alertResult.channel,
      alert_success: alertResult.success
    }, { status: 500 });
  }
}
