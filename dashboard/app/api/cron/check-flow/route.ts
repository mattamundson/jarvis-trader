import { NextResponse } from "next/server";
import { head } from "@vercel/blob";
import { logCronAlert, logHealthCheck } from "@/lib/healthLogger";
import { recordHealthCheck } from "@/lib/healthHistory";

export async function GET(request: Request) {
  const authHeader = request.headers.get("authorization");
  if (authHeader !== `Bearer ${process.env.CRON_SECRET}`) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const blobToken = process.env.BLOB_READ_WRITE_TOKEN;
  const discordWebhook = process.env.DISCORD_WEBHOOK_FLOW_ALERTS;
  
  if (!blobToken || !discordWebhook) {
    return NextResponse.json({ 
      error: "Not configured",
      has_blob: !!blobToken,
      has_webhook: !!discordWebhook 
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
      let discordSuccess = false;
      let discordStatus = 0;
      
      try {
        const discordRes = await fetch(discordWebhook, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            embeds: [{
              title: "🔴 Flow Feed STALE",
              description: `Last update: **${ageMin} minutes ago**\n\nCheck Windows pusher.`,
              color: 0xFF0000,
              timestamp,
              footer: { text: "JARVIS Flow Monitor" }
            }]
          })
        });
        discordSuccess = discordRes.ok;
        discordStatus = discordRes.status;
      } catch (discordErr) {
        console.error("Discord webhook failed:", discordErr);
      }
      
      // Log alert event
      logCronAlert({
        timestamp,
        triggered: true,
        blob_age_seconds: ageSec,
        discord_sent: discordSuccess,
        discord_response_status: discordStatus
      });
      
      return NextResponse.json({ status: "alerted", age_minutes: ageMin });
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
    
    let discordSuccess = false;
    let discordStatus = 0;
    
    try {
      const discordRes = await fetch(discordWebhook, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          embeds: [{
            title: "🔴 Flow Feed OFFLINE",
            description: `Blob unreachable.\n\nError: \`${String(err).slice(0, 200)}\``,
            color: 0xFF0000,
            timestamp
          }]
        })
      });
      discordSuccess = discordRes.ok;
      discordStatus = discordRes.status;
    } catch (discordErr) {
      console.error("Discord webhook failed:", discordErr);
    }
    
    // Log offline alert
    logCronAlert({
      timestamp,
      triggered: true,
      blob_age_seconds: -1,
      discord_sent: discordSuccess,
      discord_response_status: discordStatus
    });
    
    return NextResponse.json({ status: "error", error: String(err) }, { status: 500 });
  }
}
