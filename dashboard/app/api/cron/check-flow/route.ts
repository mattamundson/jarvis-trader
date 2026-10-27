import { NextResponse } from "next/server";
import { head } from "@vercel/blob";

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
    
    if (ageMin > 5) {
      await fetch(discordWebhook, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          embeds: [{
            title: "🔴 Flow Feed STALE",
            description: `Last update: **${ageMin} minutes ago**\n\nCheck Windows pusher.`,
            color: 0xFF0000,
            timestamp: new Date().toISOString(),
            footer: { text: "JARVIS Flow Monitor" }
          }]
        })
      });
      
      return NextResponse.json({ status: "alerted", age_minutes: ageMin });
    }
    
    return NextResponse.json({ status: "healthy", age_minutes: ageMin });
  } catch (err) {
    await fetch(discordWebhook, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        embeds: [{
          title: "🔴 Flow Feed OFFLINE",
          description: `Blob unreachable.\n\nError: \`${String(err).slice(0, 200)}\``,
          color: 0xFF0000,
          timestamp: new Date().toISOString()
        }]
      })
    });
    
    return NextResponse.json({ status: "error", error: String(err) }, { status: 500 });
  }
}
