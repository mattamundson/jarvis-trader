import { NextResponse } from "next/server";
import { getHealthHistory, calculateUptime } from "@/lib/healthHistory";
import { fetchHistoricalRecords, isKvConfigured } from "@/lib/kvHistory";
import { sendAlert } from "@/lib/alerting";
import { logCronInvocation } from "@/lib/auditLog";

export async function GET(request: Request) {
  const ip = request.headers.get("x-forwarded-for")?.split(",")[0] || "unknown";
  const authHeader = request.headers.get("authorization");
  
  const authorized = authHeader === `Bearer ${process.env.CRON_SECRET}`;
  logCronInvocation(ip, "/api/cron/weekly-report", authorized);
  
  if (!authorized) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  
  // Gather 7-day metrics
  const kvEnabled = isKvConfigured();
  const historicalRecords = kvEnabled 
    ? await fetchHistoricalRecords(7 * 24) // 7 days
    : getHealthHistory(); // Fall back to in-memory (last 100 checks only)
  
  const uptime24h = calculateUptime(24 * 60);
  const uptime7d = calculateUptime(7 * 24 * 60);
  
  // Calculate stats
  const totalChecks = historicalRecords.length;
  const liveCount = historicalRecords.filter(r => r.status === "live").length;
  const staleCount = historicalRecords.filter(r => r.status === "stale").length;
  const offlineCount = historicalRecords.filter(r => r.status === "offline").length;
  
  const avgLiveCount = totalChecks > 0 ? (liveCount / totalChecks) * 100 : 0;
  
  // Find longest outage
  let longestOutage = 0;
  let currentOutageStart: string | null = null;
  
  for (const record of historicalRecords) {
    if (record.status === "offline") {
      if (!currentOutageStart) {
        currentOutageStart = record.timestamp;
      }
    } else if (currentOutageStart) {
      const outageMs = new Date(record.timestamp).getTime() - new Date(currentOutageStart).getTime();
      longestOutage = Math.max(longestOutage, outageMs / 60000); // minutes
      currentOutageStart = null;
    }
  }
  
  const report = `
📊 **JARVIS Flow Feed — Weekly Report**

**Uptime:**
- Last 24 hours: ${uptime24h.toFixed(2)}%
- Last 7 days: ${uptime7d.toFixed(2)}%

**Health Checks (${totalChecks} total):**
- ✅ Live: ${liveCount} (${avgLiveCount.toFixed(1)}%)
- ⚠️ Stale: ${staleCount}
- 🔴 Offline: ${offlineCount}

**Longest Outage:** ${longestOutage > 0 ? `${longestOutage.toFixed(1)} minutes` : "None"}

**Data Source:** ${kvEnabled ? "Vercel KV (7 days)" : "In-memory (last 100 checks)"}
${kvEnabled ? "" : "\n⚠️ Consider enabling Vercel KV for full 7-day historical data."}
  `.trim();
  
  // Send report via alerting channel
  await sendAlert(report);
  
  console.log("[weekly-report] Report sent successfully");
  
  return NextResponse.json({ 
    status: "sent",
    uptime_24h: uptime24h,
    uptime_7d: uptime7d,
    checks: totalChecks,
    kv_enabled: kvEnabled
  });
}
